"""
Integration tests for the customer authentication flow.

register → login → protected endpoint → logout → post-logout rejection

Runs against a real Postgres container. Each test is isolated via rollback.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


class TestCustomerAuthFlow:
    """Full register-login-protected-logout lifecycle."""

    @pytest.mark.asyncio
    async def test_register_login_protected_logout_reject(
        self,
        async_client: AsyncClient,
    ) -> None:
        """
        Happy-path lifecycle:
          1. Register a new customer → 201
          2. Login with the same credentials → 200 + session_token
          3. Access a protected endpoint (add-balance) with the token → not 401
          4. Logout → 204
          5. Re-use the same token on the protected endpoint → 401
        """
        # 1. Register
        reg_response = await async_client.post(
            "/api/v1/auth/register",
            json={
                "name": "Integration User",
                "email": "integration_auth@example.com",
                "password": "securepass",
                "national_id": 55555555,
                "phone": 622222222,
            },
        )
        assert reg_response.status_code == 201, reg_response.text

        # 2. Login
        login_response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": "integration_auth@example.com",
                "password": "securepass",
            },
        )
        assert login_response.status_code == 200, login_response.text
        session_token = login_response.json()["session_token"]
        auth_headers = {"Authorization": f"Bearer {session_token}"}

        # 3. Access protected endpoint (add-balance → 200 since account exists)
        balance_response = await async_client.post(
            "/api/v1/accounts/add-balance",
            json={"amount": "10.0000"},
            headers=auth_headers,
        )
        assert balance_response.status_code == 200, balance_response.text

        # 4. Logout → 204
        logout_response = await async_client.post(
            "/api/v1/auth/logout",
            headers=auth_headers,
        )
        assert logout_response.status_code == 204, logout_response.text

        # 5. Token is now invalid → 401
        post_logout_response = await async_client.post(
            "/api/v1/accounts/add-balance",
            json={"amount": "10.0000"},
            headers=auth_headers,
        )
        assert post_logout_response.status_code == 401, post_logout_response.text

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(
        self,
        async_client: AsyncClient,
    ) -> None:
        """Wrong password → 401 without creating a session."""
        # Register first
        await async_client.post(
            "/api/v1/auth/register",
            json={
                "name": "Auth Fail User",
                "email": "auth_fail@example.com",
                "password": "correctpass",
                "national_id": 66666666,
                "phone": 633333333,
            },
        )

        response = await async_client.post(
            "/api/v1/auth/login",
            json={
                "email": "auth_fail@example.com",
                "password": "wrongpass",
            },
        )
        assert response.status_code == 401
