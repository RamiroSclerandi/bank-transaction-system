"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.api_v1.endpoints import (
    accounts,
    admin_backoffice,
    auth,
    internal,
    transactions,
)

api_router = APIRouter()

api_router.include_router(transactions.router)
api_router.include_router(auth.customer_auth_router)
api_router.include_router(auth.admin_auth_router)
api_router.include_router(admin_backoffice.router)
api_router.include_router(internal.router)
api_router.include_router(accounts.customer_accounts_router)
api_router.include_router(accounts.admin_accounts_router)
