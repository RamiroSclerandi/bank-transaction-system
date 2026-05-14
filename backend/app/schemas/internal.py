"""Pydantic schemas for internal service endpoints."""

from pydantic import BaseModel


class CronJobResult(BaseModel):
    """Summary response for cron job endpoints."""

    total: int
    processed: int
    skipped: int
    errors: int
