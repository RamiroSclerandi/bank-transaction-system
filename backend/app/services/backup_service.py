"""
Backup service — triggers a daily database snapshot.

Strategy pattern based on ENVIRONMENT:
  - development: runs pg_dump via subprocess, saves to backend/db_backups/
  - production: triggers a native AWS RDS snapshot via boto3
"""

import asyncio
import os
import re
import subprocess
from datetime import date

import boto3  # type: ignore[import-untyped]
import botocore.exceptions  # type: ignore[import-untyped]

from app.core.config import settings

_BACKUP_DIR = "db_backups"


def _parse_db_url_for_pg_dump(database_url: str) -> list[str]:
    """
    Parse a SQLAlchemy async DATABASE_URL and return pg_dump CLI arguments.

    Handles URLs in the form:
        postgresql+asyncpg://user:pass@host:port/dbname
        postgresql://user:pass@host/dbname
    """
    # Strip driver prefix so urlparse works cleanly
    clean = re.sub(r"^postgresql\+[^:]+://", "postgresql://", database_url)
    match = re.match(
        r"postgresql://(?P<user>[^:@]+)(?::(?P<password>[^@]*))?@"
        r"(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<dbname>[^?]+)",
        clean,
    )
    if not match:
        raise ValueError(f"Cannot parse DATABASE_URL for pg_dump: {database_url!r}")

    user = match.group("user")
    host = match.group("host")
    port = match.group("port") or "5432"
    dbname = match.group("dbname")

    return ["pg_dump", "-h", host, "-p", port, "-U", user, "-d", dbname]


async def _run_development_backup() -> dict[str, str]:
    """Run a local pg_dump backup; store in db_backups/."""
    today = date.today().isoformat()
    filename = f"daily-snapshot-{today}.sql"

    os.makedirs(_BACKUP_DIR, exist_ok=True)
    output_path = os.path.join(_BACKUP_DIR, filename)

    pg_args = _parse_db_url_for_pg_dump(settings.DATABASE_URL)
    cmd = pg_args + ["-f", output_path]

    process = await asyncio.create_subprocess_exec(*cmd)
    await process.communicate()

    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode or 1, cmd)

    return {"snapshot_id": filename, "status": "completed"}


async def _run_production_backup() -> dict[str, str]:
    """Trigger a native AWS RDS snapshot via boto3."""
    today = date.today().isoformat()
    snapshot_id = f"daily-snapshot-{today}"

    rds = boto3.client("rds", region_name=settings.AWS_REGION)  # type: ignore[no-untyped-call]

    def _create_snapshot() -> dict[str, str]:
        response = rds.create_db_snapshot(  # type: ignore[no-untyped-call]
            DBSnapshotIdentifier=snapshot_id,
            DBInstanceIdentifier=settings.AWS_RDS_INSTANCE_IDENTIFIER,
        )
        return {"status": response["DBSnapshot"]["Status"]}  # type: ignore[no-untyped-dict-access]

    try:
        result = await asyncio.to_thread(_create_snapshot)
        status = result["status"]
    except botocore.exceptions.ClientError as exc:
        error_code = exc.response["Error"]["Code"]  # type: ignore[no-untyped-dict-access]
        if error_code == "DBSnapshotAlreadyExists":
            return {"snapshot_id": snapshot_id, "status": "already_exists"}
        raise

    return {"snapshot_id": snapshot_id, "status": status}


async def execute_daily_backup() -> dict[str, str]:
    """
    Execute the daily backup based on the current environment.

    In development: runs pg_dump and saves to db_backups/.
    In production: triggers an AWS RDS snapshot via boto3.

    Returns
    -------
        A dict with ``snapshot_id`` and ``status`` keys.

    """
    if settings.ENVIRONMENT == "development":
        return await _run_development_backup()
    return await _run_production_backup()
