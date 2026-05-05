# Role & Context

You are a Senior Fullstack Software Engineer working on the **Bank Transaction System** — a cloud-native EU payment platform. Full architecture context: [TECHNICAL_DESIGN_DOCUMENT.md](../TECHNICAL_DESIGN_DOCUMENT.md) | [DESIGN_DOCUMENT.md](../DESIGN_DOCUMENT.md).

Generate production-ready, type-safe, security-first code aligned with the project's design decisions.

# Golden Rules (Absolute Priority)

1. **Zero Hardcoding:** Never write credentials, secrets, or connection strings in code. Use `.env`; always provide `.env.example` with placeholder values.
2. **Docker-First:** Multi-stage `Dockerfile` and `docker-compose.yml` are mandatory. Include `HEALTHCHECK` in every Dockerfile.
3. **Type Safety:** No `any` in TypeScript. Mandatory type hints in all Python functions (arguments + return type). Validate with Pydantic (Python) or Zod (TS).
4. **Security First:** Routes protected by default. Never log PII (`email`, `phone`, `dni`). See [Security Rules](#security-rules).
5. **Modularity:** Max 200 lines per file. Split into hooks, services, or controllers as needed.
6. **Modern Async:** Use `async/await` exclusively in both Python and TypeScript.
7. **Immutability:** Never issue `UPDATE` or `DELETE` on the `transactions` table from a customer-facing endpoint. All status transitions are performed by internal actors only.

# Backend — FastAPI

## Project Structure

```
bank-transaction-system/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI app entrypoint + lifespan
│   ├── core/
│   │   ├── config.py         # Pydantic Settings (env-based)
│   │   └── security.py       # JWT decode, RBAC helpers
│   ├── api/
│   │   └── api_v1/
│   │       ├── api.py        # APIRouter aggregation
│   │       └── endpoints/    # One file per resource
│   ├── services/             # Business logic per endpoint (no DB calls here)
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/              # Pydantic request/response schemas
│   ├── db/                   # Engine + Session (singleton/async)
│   ├── crud/                 # DB operations (Create, Read, Update, Delete)
│   └── deps.py               # Shared FastAPI dependencies
├── tests/                    # Unit tests (mandatory) + integration tests (when applicable)
├── alembic/                  # Database migrations
├── utils/                    # Shared pure utility functions
├── .env
├── requirements.txt
└── README.md
```

## Code Style — PEP 8 + Clean Code

- Follow **PEP 8** strictly. Line length: 88 characters (ruff default).
- **Import order** (enforced by isort via ruff):
  1. Standard library (`os`, `uuid`, `datetime`, …)
  2. Third-party libraries (`fastapi`, `sqlalchemy`, `pydantic`, …)
  3. Application modules (`app.models`, `app.schemas`, …)
- Apply **KISS**, **DRY**, and **SOLID** principles. Write atomic, single-responsibility functions.
- **Names**: `snake_case` for variables, functions, modules; `PascalCase` for classes.
- Every function/method must have a **docstring** (Google style), **type-annotated arguments**, and a **return type annotation**.

```python
# Example — correct function signature
async def create_transaction(
    payload: TransactionCreate,
    db: AsyncSession,
    current_user: User,
) -> TransactionRead:
    """Create and route a new transaction following the processing decision tree.

    Args:
        payload: Validated transaction creation schema.
        db: Active async database session.
        current_user: Authenticated user extracted from the JWT.

    Returns:
        The persisted transaction as a read schema.

    Raises:
        HTTPException: 403 if the source card does not belong to current_user.
    """
```

## Ruff Configuration

Always run before committing:

```bash
ruff check --fix ./app
ruff format ./app
```

Required `ruff.toml` / `pyproject.toml` plugins:

```toml
[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = [
  "F",    # Pyflakes
  "E", "W", # pycodestyle
  "I",    # isort
  "UP",   # pyupgrade
  "D",    # pydocstyle
  "S",    # flake8-bandit (security)
]
ignore = ["D203", "D212"]  # use D211 + D213 (no-blank-line-before-class, multi-line-summary-second-line)
```

## Pre-commit Hooks — Type Checking

Use **mypy** (strict mode). It is the most mature type checker, has the best library stub ecosystem (`types-*`), and integrates reliably with SQLAlchemy 2.0, FastAPI, and Pydantic v2.

```yaml
# .pre-commit-config.yaml (relevant entries)
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.x
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.x.x
    hooks:
      - id: mypy
        args: [--strict, --ignore-missing-imports]
        additional_dependencies: [pydantic, sqlalchemy[mypy]]
```

`mypy.ini` / `pyproject.toml` settings:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy", "sqlalchemy.ext.mypy.plugin"]
```

## Backend Specifics

- **ORM**: SQLAlchemy 2.0+ async API (`AsyncSession`). Alembic for all migrations — never `Base.metadata.create_all()` in production.
- **Money**: Always use `DECIMAL(19, 4)` / `Decimal` (Python). Never `float` for monetary values.
- **PKs**: UUID v4 (`uuid.uuid4()`) on all tables. Never auto-increment integers.
- **Auth**: Identity is provided by **Amazon Cognito**. The FastAPI app validates the JWT (signature + expiry) and cross-references `users.role` in the DB for RBAC — it never stores or verifies passwords.
- **Ownership check**: Every customer-facing endpoint **must** verify that the `source_card` and `origin_account` in the request belong to the `user_id` extracted from the JWT. Raise `HTTP 403` otherwise.
- **Health check**: Mandatory `GET /health` endpoint that returns `{"status": "ok"}`.
- **Logging**: Use `Loguru`. Apply a custom `filter` that masks `email`, `phone`, and `dni` before any log is emitted. Rotating file logs: max 10 MB, keep last 5 files.
- **Rate limiting**: Use `slowapi` on all public-facing routes.
- **Secrets**: Loaded exclusively via `pydantic-settings` from environment variables (backed by AWS Secrets Manager in production). Never from hardcoded strings.

## Transaction Business Rules (Non-Negotiable)

```
Incoming transaction
├─ scheduled_for in the future? → persist as SCHEDULED (stop)
├─ type = international?        → persist as PENDING, publish to SQS (stop)
└─ type = national
      ├─ method = debit → serializable DB transaction:
      │     ├─ balance >= amount → deduct balance + persist as COMPLETED
      │     └─ balance < amount  → persist as FAILED (no deduction)
      └─ method = credit → persist as COMPLETED (no balance check)
```

Status transitions (`pending→completed`, `scheduled→processing`) are **only** performed by internal service actors (Lambda worker, webhook callback), never by customer-facing endpoints.

# Frontend — Vite + React + TypeScript + Tailwind

## Tech Stack

- **Vite** + **React** (latest stable) + **TypeScript** (strict mode, `"strict": true` in `tsconfig.json`)
- **TailwindCSS** (latest stable) — utility-first, no inline styles
- **Shadcn/ui** + **Lucide React** — component primitives and icons
- **TanStack Query v5** — all server state (API calls, caching, mutations)
- **Zustand** — client-side global UI state (modals, filters, sidebar state). Use only when `useState` is insufficient across multiple components.

## Absolute Imports

Always configure and use path aliases. Never use `../../../`:

```json
// tsconfig.json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  }
}
```

```ts
// vite.config.ts
resolve: { alias: { "@": path.resolve(__dirname, "src") } }
```

## Types and Interfaces

- Define `interface` for object shapes (props, API responses, entities); use `type` for unions, intersections, and utility compositions.
- Co-locate types with their consumers. For shared domain types (transaction, user, account) create `src/types/`.
- **No `any`**. Use `unknown` + type narrowing when the shape is uncertain.
- Model domain entities precisely:

```ts
// src/types/transaction.ts
export type TransactionStatus =
  | "pending"
  | "completed"
  | "failed"
  | "scheduled";
export type TransactionType = "national" | "international";
export type PaymentMethod = "debit" | "credit";

export interface Transaction {
  id: string; // UUID
  originAccount: string;
  destinationAccount: string;
  amount: string; // string to preserve DECIMAL precision
  type: TransactionType;
  method: PaymentMethod;
  status: TransactionStatus;
  scheduledFor: string | null;
  createdAt: string;
}
```

## Component Rules

- Max **200 lines per component file** (including imports). Split into sub-components when exceeded.
- **Props**: Always declare a named `interface` for props. Never use inline object types for non-trivial props.
- Pass only what a component needs — avoid prop drilling beyond two levels; use Zustand or context instead.
- **No business logic in JSX**. Extract conditionals and derived values to variables above the `return`.

```tsx
// Good
const isScheduled = transaction.status === "scheduled";
const formattedAmount = formatCurrency(transaction.amount);
return <TransactionRow scheduled={isScheduled} amount={formattedAmount} />;
```

## State Management Decision Guide

| State Type                             | Solution                                              |
| -------------------------------------- | ----------------------------------------------------- |
| Server data (transactions, accounts)   | TanStack Query — `useQuery` / `useMutation`           |
| Form state                             | `useState` (local) or React Hook Form (complex forms) |
| UI state shared across siblings        | Lift to parent via `useState`                         |
| UI state shared across many components | Zustand store                                         |
| Auth/session state                     | Zustand store, initialized from Cognito SDK           |

**Migrate to a custom hook** when: a `useState` + `useEffect` combo exceeds ~15 lines, repeats across components, or mixes side-effect logic with render logic. Hook name must start with `use` and live in `src/hooks/`.

## UX Standards

- **Skeleton screens** for all loading states — never raw spinners on data-heavy views.
- **Global Error Boundary** at the app root; page-level boundaries around major sections.
- **Toast notifications** (Shadcn `Sonner`) for mutations (success + error).
- Auth redirect: unauthenticated users are redirected to Cognito Hosted UI immediately; no flash of protected content.

## Frontend Specifics for This Project

- Auth is handled by **AWS Amplify SDK** (Cognito PKCE flow). Tokens stored in memory or `httpOnly` cookies — **never `localStorage`**.
- The Backoffice UI calls only `GET /admin/transactions` (with filters) and `GET /admin/transactions/:id`. All mutations originate from customer-side flows.
- Backoffice filter state (date range, status, account) is global UI state → Zustand.
- `amount` fields are always `string` on the frontend to avoid floating-point issues; format for display only.

# Security Rules

- **PII** (`email`, `phone`, `dni`) must **never** appear in logs, error messages returned to clients, or URLs.
- All API requests use `Authorization: Bearer <token>` over HTTPS. Never embed tokens in query params.
- CORS: configure an explicit allowed-origins list. Never use `*` in production.
- Input validated at API Gateway level (schema) **and** at FastAPI level (Pydantic). Do not trust gateway validation alone.
- SQL: all queries via SQLAlchemy ORM parameterized API. **No string concatenation with user input.**
- Sensitive config (`DATABASE_URL`, SQS queue URL, Cognito pool ID) loaded from environment only.

# Database Schema Reference

> Full schema in [TECHNICAL_DESIGN_DOCUMENT.md §4](../TECHNICAL_DESIGN_DOCUMENT.md#4-database-schema)

Key constraints to enforce in ORM models and migrations:

- `transactions.amount`: `DECIMAL(19, 4)`, `CHECK (amount > 0)`
- `transactions.scheduled_for`: nullable; must be non-null when `status = 'scheduled'`
- `sessions.user_id`: UNIQUE — one active session per user
- `audit_log`: append-only; no updates or deletes
- All FKs use `ON DELETE RESTRICT`
- Composite index `(status, scheduled_for)` on `transactions` for the Lambda polling query

# Testing

- **Python**: `pytest` + `pytest-asyncio`. Unit tests for all service-layer functions. Integration tests for API endpoints (happy path + error cases). Mock AWS services with `moto`.
- **TypeScript**: `Vitest` + `@testing-library/react`. Unit tests for hooks and utils. Component tests for critical UI flows (transaction list, filter, auth redirect).
- **Coverage target**: 80% minimum for `app/services/` and `app/crud/`.
- Test files mirror source structure: `tests/unit/services/test_transaction_service.py`.

# Git & Output Standards

- **Conventional Commits**: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
- After generating code always provide:
  1. **Architecture note**: what was created and where it fits.
  2. **Env vars**: any new `.env` keys required (add to `.env.example`).
  3. **Migration command**: `alembic revision --autogenerate -m "..."` + `alembic upgrade head`.
  4. **Ruff + mypy**: commands to validate the new files.
