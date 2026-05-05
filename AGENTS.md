# Bank Transaction System — Agent Instructions

## Project Overview

A cloud-native payment platform for an EU-based bank. Two components:

- **Transaction Service**: FastAPI backend (Python 3.12+) handling payment creation, routing, and balance management
- **Backoffice UI**: React SPA for authenticated bank staff to monitor transactions (frontend not yet built)

Full design context: [DESIGN_DOCUMENT.md](documents/DESIGN_DOCUMENT.md)

## Current Implementation State

- Backend is **fully implemented and tested** (29/29 tests passing).
- Auth is **custom session-based** — bcrypt password hashing + opaque tokens (SHA-256 digest stored in DB). No Cognito.
- Database is **PostgreSQL** (not MySQL). ORM: SQLAlchemy 2.0 async with `asyncpg`.
- Package manager: **uv** (`pyproject.toml` + `uv.lock`). No `requirements.txt`.
- Alembic initial migration exists at `backend/alembic/versions/20260505_1545_initial_schema.py`.
- Frontend is **not yet built**.

## Architecture

| Layer       | Technology                               | Notes                                                               |
| ----------- | ---------------------------------------- | ------------------------------------------------------------------- |
| Frontend    | React SPA _(planned)_                    | S3 + CloudFront; not yet implemented                                |
| Backend     | FastAPI on Docker → target AWS ECS EC2   | Stateless; Pydantic validation; async throughout                    |
| Auth        | Custom session tokens                    | bcrypt + opaque token; SHA-256 hash stored in DB; 1-hour TTL        |
| Queue       | AWS SQS                                  | International payment pipeline; DLQ required                        |
| Scheduler   | EventBridge + Lambda                     | 1-min cron; polls DB for `status='scheduled'`                       |
| Database    | PostgreSQL 16 on AWS RDS                 | SQLAlchemy 2.0 async ORM; Alembic migrations                        |
| Logging     | loguru                                   | PII masking filter on all log records                               |

## Core Invariants — Never Violate

1. **Transactions are immutable.** No `UPDATE` or `DELETE` on the `transactions` table from customer-facing endpoints. Status transitions (`pending → completed`, etc.) are only performed by internal actors (Lambda worker, webhook callback).
2. **Balance deduction is atomic.** The balance check and deduction for debit transactions MUST occur in a single serializable database transaction.
3. **No raw SQL.** All queries MUST use SQLAlchemy's ORM/parameterized query API. Never concatenate user input into SQL strings.
4. **Secrets never in code.** Credentials and keys come exclusively from environment variables (dev) or AWS Secrets Manager (production). Never hardcoded.
5. **PII never in logs.** `email`, `phone`, and `national_id` fields MUST be masked before any log is emitted (`utils/logging.py` `_mask_pii` filter).

## Transaction Processing Decision Tree

```
Incoming transaction
├─ scheduled_for in the future? → persist as SCHEDULED (stop; Lambda handles later)
├─ type = international?        → persist as PENDING, publish to SQS (stop; external processor handles)
└─ type = national
      ├─ method = debit → check balance
      │     ├─ sufficient   → deduct balance + persist as COMPLETED (one atomic DB tx)
      │     └─ insufficient → persist as FAILED
      └─ method = credit → persist as COMPLETED immediately (no balance check)
```

## Database Schema (Key Tables)

- `users(id UUID PK, name, national_id BIGINT UNIQUE, email UNIQUE, phone BIGINT UNIQUE, password_hash, role ENUM('admin','customer'), registered_ip VARCHAR(45), created_at, updated_at)`
- `accounts(id UUID PK, user_id FK UNIQUE, balance DECIMAL(19,4), created_at)`
- `cards(id UUID PK, account_id FK, card_type ENUM('debit','credit'), created_at)`
- `transactions(id UUID PK, source_card FK, origin_account FK, destination_account VARCHAR(255), amount DECIMAL(19,4) CHECK>0, type ENUM('national','international'), method ENUM('debit','credit'), status ENUM('pending','completed','failed','scheduled','processing'), scheduled_for DATETIME NULL, reversal_of UUID FK NULL, created_at)`
- `sessions(id UUID PK, user_id FK UNIQUE, token_hash VARCHAR(255), ip_address VARCHAR(45), expires_at, created_at)` — **deleted on logout**; one active session per user
- `audit_logs(id UUID PK, user_id FK, action ENUM('login','logout','login_failed'), ip_address VARCHAR(45), timestamp)` — append-only

Always use `DECIMAL(19,4)` for monetary values, never `FLOAT`.

## Auth Architecture

- **Admin endpoints** (`/api/v1/admin/*`): require `AdminDep` — token must belong to a user with `role='admin'`.
- **Customer endpoints** (`/api/v1/transactions/*`): require `CustomerDep` — token must belong to a user with `role='customer'`.
- **Internal endpoints** (`/api/v1/internal/*`): require `X-Internal-Key` header matching `INTERNAL_SERVICE_API_KEY` env var.
- Session token flow: raw token returned to client → SHA-256 digest stored in `sessions.token_hash`. On every request, the presented token is hashed and compared.

## Security Rules

- Every customer endpoint MUST verify that the `source_card` and `origin_account` in the request belong to the authenticated user's `user_id` (ownership enforcement).
- `users.role` in the database is the authoritative RBAC source — always check against DB, not just the session.
- All tokens are transmitted only via `Authorization: Bearer` over TLS; never in URLs or cookies.
- No `UPDATE` on any column in the `transactions` table except `status` (enforced at application layer).

## Scheduling & Idempotency

The EventBridge Lambda uses an optimistic lock to prevent double-processing:

```sql
UPDATE transactions SET status = 'processing'
WHERE id = :id AND status = 'scheduled' AND scheduled_for <= NOW()
```

Only the invocation that claims the row proceeds.

## Key Technology Choices & Rationale

- **Custom session auth over Cognito**: full control over single-session-per-user enforcement, IP binding, and audit logging — none of which Cognito supports natively.
- **ECS EC2 over Lambda** for the main service: eliminates cold-start latency for synchronous transaction endpoints.
- **EventBridge + Lambda over SQS Delay Queue** for scheduling: DB is single source of truth; SQS max 15-min delay can't handle future-dated transactions.
- **SQS over direct HTTP** for international payments: durability, DLQ, decoupling from external processor availability.
- **PostgreSQL over MySQL**: superior support for UUIDs, ENUM types, and advisory locks.

## Project Structure

```
backend/
├── app/
│   ├── api/api_v1/endpoints/   # admin_auth, admin_backoffice, customer_auth, transactions, internal
│   ├── core/                   # config.py (pydantic-settings), security.py (hashing/tokens)
│   ├── crud/                   # one module per model; all async
│   ├── models/                 # SQLAlchemy ORM models; __init__.py imports all for Alembic
│   ├── schemas/                # Pydantic v2 schemas
│   ├── services/               # Business logic: transaction_service, admin_service, sqs_service
│   └── deps.py                 # FastAPI dependencies: AdminDep, CustomerDep, get_db
├── alembic/                    # DB migrations
├── scripts/                    # seed_admin.py — creates first admin user from env vars
├── tests/unit/services/        # pytest-asyncio; 29 tests
└── utils/logging.py            # loguru setup with PII masking
```

## Out of Scope

Card issuance, credit limit management, KYC/onboarding, fraud detection, AML, chargeback management, multi-currency conversion, cross-region DR.
