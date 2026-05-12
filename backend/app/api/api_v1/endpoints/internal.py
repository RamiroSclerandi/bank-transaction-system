"""
Internal service endpoints, called by Lambda workers, not by customers.
These routes are protected by the X-Internal-Api-Key header (shared secret).
"""

import uuid

from fastapi import APIRouter, status

from app.deps import DbDep, InternalAuthDep
from app.schemas.transaction import TransactionRead
from app.services import archive_service, backup_service, transaction_service

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post(
    "/transactions/{transaction_id}/process",
    response_model=TransactionRead,
    status_code=status.HTTP_200_OK,
    summary="Process a due scheduled transaction (Lambda worker only)",
)
async def process_scheduled(
    transaction_id: uuid.UUID,
    db: DbDep,
    _auth: InternalAuthDep,
) -> TransactionRead:
    """
    Trigger processing of a scheduled transaction that is now due. It's
    called by the EventBridge Lambda every minute for each due scheduled
    transaction. Uses an optimistic lock to guarantee idempotency — if two
    Lambda invocations race, only one will successfully claim the row.

    Args:
    ----
        transaction_id: UUID of the scheduled transaction to process.
        db: Injected database session.
        _auth: Internal API key validation (no return value needed).

    Returns:
    -------
        The updated transaction resource.

    Raises:
    ------
        HTTPException: 404 if the transaction does not exist.
        HTTPException: 409 if another worker already claimed the transaction.

    """
    transaction = await transaction_service.process_scheduled_transaction(
        transaction_id=transaction_id,
        db=db,
    )
    return TransactionRead.model_validate(transaction)


@router.post(
    "/jobs/archive-transactions",
    status_code=status.HTTP_200_OK,
    summary="Copy completed/failed transactions to history table (Lambda worker only)",
)
async def run_archive_transactions(
    db: DbDep,
    _auth: InternalAuthDep,
) -> dict[str, int]:
    """
    Idempotent copy of completed/failed transactions into the transaction_history
    data warehouse table. Called by the daily EventBridge Lambda.

    Args:
    ----
        db: Injected database session.
        _auth: Internal API key validation.

    Returns:
    -------
        ``{"rows_archived": N}`` — number of rows copied in this invocation.

    """
    rows_archived = await archive_service.copy_transactions_to_history(db=db)
    return {"rows_archived": rows_archived}


@router.post(
    "/jobs/daily-backup",
    status_code=status.HTTP_200_OK,
    summary="Trigger daily RDS snapshot or pg_dump backup (Lambda worker only)",
)
async def run_daily_backup(
    _auth: InternalAuthDep,
) -> dict[str, str]:
    """
    Trigger the daily database backup. In development, runs pg_dump and saves
    to db_backups/. In production, triggers an AWS RDS snapshot via boto3.

    Args:
    ----
        _auth: Internal API key validation.

    Returns:
    -------
        ``{"snapshot_id": ..., "status": ...}`` — snapshot name and AWS/local status.

    """
    return await backup_service.execute_daily_backup()
