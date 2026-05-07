"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.api_v1.endpoints import (
    admin_backoffice,
    auth,
    customer_auth,
    internal,
    transactions,
)

api_router = APIRouter()

api_router.include_router(transactions.router)
api_router.include_router(customer_auth.router)
api_router.include_router(auth.customer_auth_router)
api_router.include_router(auth.admin_auth_router)
api_router.include_router(admin_backoffice.router)
api_router.include_router(internal.router)
