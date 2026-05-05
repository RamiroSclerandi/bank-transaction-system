# Bank Transaction System

An internal transaction platform built for a small EU-based online bank. It handles both domestic (national) and international payment transfers, provides a monitoring interface for bank staff, and is designed from the ground up to be secure, reliable, and easy to scale.

---

## What the system does

- **Processes payments** — customers can submit national or international transfers using debit or credit cards.
- **Handles scheduled payments** — transactions can be set for a future date; the system executes them automatically within a 5-minute window.
- **Routes international payments asynchronously** — international transfers are queued and handed off to an external processor, keeping the system decoupled from third-party availability.
- **Provides a staff monitoring interface** — a separate backoffice UI lets authorized bank employees search for transactions by ID, filter by account and date range, and view the full history.
- **Keeps a full audit trail** — every login attempt (successful or not) and every logout is permanently recorded.

## What it does NOT do

Card issuance, credit limit management, customer onboarding, fraud detection, or currency conversion are outside the scope of this system.

---

## How it works (non-technical overview)

```
Customer / External Service
        │  HTTPS
        ▼
  Transaction API  ──── PostgreSQL database
        │
        ├── National payment   → processed immediately
        ├── International      → queued → external processor
        └── Scheduled payment  → stored → executed automatically later

Bank Staff Browser
        │  HTTPS
        ▼
  Backoffice UI  ──── same Transaction API (read-only views)
```

All communication happens over encrypted HTTPS connections. Sensitive fields (email, phone, national ID) are masked in application logs.

---

## Technical stack

| Layer                 | Technology                                       |
| --------------------- | ------------------------------------------------ |
| Backend API           | Python 3.12 · FastAPI · Uvicorn                  |
| Database              | PostgreSQL 16 · SQLAlchemy 2.0 (async) · Alembic |
| Auth                  | Custom session tokens (bcrypt + SHA-256)         |
| Async messaging       | AWS SQS                                          |
| Scheduling            | AWS EventBridge + Lambda                         |
| Packaging             | uv                                               |
| Linting / types       | Ruff · Mypy                                      |
| Tests                 | Pytest (29 passing)                              |
| Infrastructure target | Docker · AWS ECS · AWS RDS                       |

For full architecture decisions, data model, and security design, see the [Technical Design Document](documents/DESIGN_DOCUMENT.md).

---

## Getting started (local development)

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (`pip install uv` or see the docs)
- Docker (for running PostgreSQL locally)
- AWS credentials configured if you need SQS

### 1. Clone and configure environment

```bash
git clone <repo-url>
cd bank-transaction-system
cp .env.example .env
# Edit .env and fill in the required values (see comments in the file)
```

### 2. Start the database

```bash
docker compose up db -d
```

### 3. Install dependencies and run migrations

```bash
cd backend
uv sync
uv run alembic upgrade head
```

### 4. Seed the first admin user

```bash
# Make sure ADMIN_PASSWORD is set in .env first
uv run python scripts/seed_admin.py
```

### 5. Start the API

```bash
uv run uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## Project structure

```
bank-transaction-system/
├── backend/
│   ├── app/
│   │   ├── api/          # HTTP route handlers
│   │   ├── core/         # Config, security utilities
│   │   ├── crud/         # Database access layer
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic request/response schemas
│   │   └── services/     # Business logic
│   ├── alembic/          # Database migrations
│   ├── scripts/          # Operational scripts (seed admin, etc.)
│   ├── tests/            # Automated tests
│   └── utils/            # Shared utilities (logging)
├── documents/            # Architecture diagram, ERD, design document
├── docker-compose.yml    # Full stack (API + DB)
├── .env.example          # Environment variable template
└── README.md
```

---

## Running tests

```bash
cd backend
uv run pytest
```

---

## Security notes

- Never commit `.env` to version control — it contains credentials.
- `ADMIN_PASSWORD` must be set before running `seed_admin.py` in any non-local environment.
- `INTERNAL_SERVICE_API_KEY` must be a strong random secret (32+ bytes) in production.
- All secrets in production should be injected from AWS Secrets Manager, not environment variables.
