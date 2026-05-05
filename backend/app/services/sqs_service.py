"""
SQS publishing service for international payment routing. It publishes a message
to the configured SQS queue when a transaction of type 'international' is created.
The external payment processor consumes these messages independently and calls back
via the webhook endpoint.
"""

import asyncio
import json
from typing import Any

import boto3  # type: ignore[import-untyped]  # no boto3-stubs installed
from loguru import logger

from app.core.config import settings
from app.models.transaction import Transaction


def _get_sqs_client() -> Any:
    """
    Create a boto3 SQS client using environment-configured credentials.

    Returns
    -------
        A boto3 SQS client.

    """
    return boto3.client("sqs", region_name=settings.AWS_REGION)


async def publish_international_payment(transaction: Transaction) -> None:
    """
    Publish an international payment message to the SQS queue.
    Runs the blocking boto3 call in a thread-pool executor to avoid
    blocking the event loop.

    Args:
    ----
        transaction: The persisted Transaction to publish. Must have
            status=pending and type=international.

    Raises:
    ------
        Exception: If the SQS send_message call fails. The caller should
            decide whether to roll back the transaction record.

    """
    message_body = json.dumps(
        {
            "transaction_id": str(transaction.id),
            "origin_account": str(transaction.origin_account),
            "destination_account": transaction.destination_account,
            "amount": str(transaction.amount),
            "method": transaction.method.value,
        }
    )

    loop = asyncio.get_event_loop()

    def _send() -> dict[str, Any]:
        client = _get_sqs_client()
        return client.send_message(  # type: ignore[no-any-return]
            QueueUrl=settings.SQS_INTERNATIONAL_QUEUE_URL,
            MessageBody=message_body,
            MessageGroupId=str(transaction.origin_account),  # for FIFO queues
        )

    try:
        response = await loop.run_in_executor(None, _send)
        logger.info(
            "SQS message published for transaction {transaction_id}. "
            "MessageId={message_id}",
            transaction_id=transaction.id,
            message_id=response.get("MessageId"),
        )
    except Exception:
        logger.exception(
            "Failed to publish SQS message for transaction {transaction_id}",
            transaction_id=transaction.id,
        )
        raise
