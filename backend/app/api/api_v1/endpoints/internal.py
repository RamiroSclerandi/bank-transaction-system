"""
Internal service endpoints, called by Lambda workers, not by customers.
These routes are protected by the X-Internal-Api-Key header (shared secret).
"""

import logging
import subprocess
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.crud.transaction import crud_transaction
from app.db.session import AsyncSessionLocal
from app.deps import DbDep, InternalAuthDep
from app.schemas.internal import CronJobResult
from app.schemas.transaction import TransactionRead
from app.services import archive_service, backup_service, transaction_service

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Archive transactions job
# ---------------------------------------------------------------------------


async def _run_archive_in_background() -> None:
    """Background coroutine: copy completed/failed transactions to history."""
    job = "archive-transactions"
    try:
        async with AsyncSessionLocal() as db:
            rows = await archive_service.copy_transactions_to_history(db=db)
        logger.info(
            "internal_job_completed job=%s status=success rows_archived=%d",
            job,
            rows,
        )
    except SQLAlchemyError:
        logger.exception("internal_job_completed job=%s status=db_error", job)
    except Exception:
        logger.exception("internal_job_completed job=%s status=unexpected_error", job)


@router.post(
    "/jobs/archive-transactions",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Copy completed/failed transactions to history table (Lambda worker only)",
)
async def run_archive_transactions(
    background_tasks: BackgroundTasks,
    _auth: InternalAuthDep,
) -> dict[str, str]:
    """
    Schedule an idempotent copy of completed/failed transactions into the
    transaction_history data warehouse table. Returns 202 immediately and
    runs the work in a background task so Lambda is not kept waiting.

    Args:
    ----
        background_tasks: FastAPI BackgroundTasks for post-response execution.
        _auth: Internal API key validation.

    Returns:
    -------
        ``{"status": "accepted", "job": "archive-transactions"}``

    """
    background_tasks.add_task(_run_archive_in_background)
    return {"status": "accepted", "job": "archive-transactions"}


# ---------------------------------------------------------------------------
# Cron: process scheduled transactions
# ---------------------------------------------------------------------------


async def _run_cron_in_background() -> None:
    """Background coroutine: fetch and process all due scheduled transactions."""
    job = "cron-process-scheduled"
    try:
        async with AsyncSessionLocal() as db:
            ids = await crud_transaction.get_due_ids(db)
            processed = skipped = errors = 0

            for tid in ids:
                try:
                    await transaction_service.process_scheduled_transaction(
                        db=db, transaction_id=tid
                    )
                    processed += 1
                except HTTPException as exc:
                    if exc.status_code == status.HTTP_409_CONFLICT:
                        skipped += 1
                    else:
                        logger.exception("HTTP error processing transaction %s", tid)
                        errors += 1
                except Exception:
                    logger.exception("Error processing transaction %s", tid)
                    errors += 1

        result = CronJobResult(
            total=len(ids), processed=processed, skipped=skipped, errors=errors
        )
        logger.info(
            "internal_job_completed job=%s status=success"
            " total=%d processed=%d skipped=%d errors=%d",
            job,
            result.total,
            result.processed,
            result.skipped,
            result.errors,
        )
    except Exception:
        logger.exception("internal_job_completed job=%s status=unexpected_error", job)


@router.post(
    "/cron/process-scheduled",
    status_code=status.HTTP_202_ACCEPTED,
    summary=(
        "Trigger sequential processing of all due scheduled transactions"
        " (Lambda cron only)"
    ),
)
async def process_scheduled_transactions(
    background_tasks: BackgroundTasks,
    _auth: InternalAuthDep,
) -> dict[str, str]:
    """
    Schedule sequential fetch-and-process of all due scheduled transactions.
    Returns 202 immediately; work runs in a background task so Lambda is not
    blocked while ECS processes the queue.

    Args:
    ----
        background_tasks: FastAPI BackgroundTasks for post-response execution.
        _auth: Internal API key validation (no return value needed).

    Returns:
    -------
        ``{"status": "accepted", "job": "cron-process-scheduled"}``

    """
    background_tasks.add_task(_run_cron_in_background)
    return {"status": "accepted", "job": "cron-process-scheduled"}


# ---------------------------------------------------------------------------
# Daily backup job
# ---------------------------------------------------------------------------


async def _run_daily_backup_in_background() -> None:
    """Background coroutine: execute the daily database backup."""
    job = "daily-backup"
    try:
        result = await backup_service.execute_daily_backup()
        logger.info(
            "internal_job_completed job=%s",
            "status=success snapshot_id=%s backup_status=%s",
            job,
            result.get("snapshot_id", "unknown"),
            result.get("status", "unknown"),
        )
    except FileNotFoundError:
        logger.exception("internal_job_completed job=%s status=not_found_error", job)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            stderr_detail = stderr.decode("utf-8", errors="replace").strip()
        elif stderr is not None:
            stderr_detail = str(stderr).strip()
        else:
            stderr_detail = ""
        stderr_detail = stderr_detail[:500] if stderr_detail else "no stderr output"
        logger.exception(
            "internal_job_completed job=%s status=process_error exit_code=%s stderr=%s",
            job,
            exc.returncode,
            stderr_detail,
        )
    except ValueError:
        logger.exception("internal_job_completed job=%s status=value_error", job)
    except Exception:
        logger.exception("internal_job_completed job=%s status=unexpected_error", job)


@router.post(
    "/jobs/daily-backup",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger daily RDS snapshot or pg_dump backup (Lambda worker only)",
)
async def run_daily_backup(
    background_tasks: BackgroundTasks,
    _auth: InternalAuthDep,
) -> dict[str, str]:
    """
    Schedule the daily database backup. Returns 202 immediately and runs the
    backup in a background task. In development, runs pg_dump; in production,
    triggers an AWS RDS snapshot.

    Args:
    ----
        background_tasks: FastAPI BackgroundTasks for post-response execution.
        _auth: Internal API key validation.

    Returns:
    -------
        ``{"status": "accepted", "job": "daily-backup"}``

    """
    background_tasks.add_task(_run_daily_backup_in_background)
    return {"status": "accepted", "job": "daily-backup"}
