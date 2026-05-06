# Bank Transaction System

An internal payment platform for a small EU-based online bank. Handles domestic and international transfers, scheduled payments, and gives bank staff a read-only view to monitor activity.

## What the system does

- **Processes payments**: Customers can submit national or international transfers using debit or credit cards.
- **Handles scheduled payments**: Transactions can be set for a future date; the system executes them automatically within a 5-minute window.
- **Routes international payments asynchronously**: International transfers go into a queue and are picked up by an external processor.
- **Provides a staff monitoring interface**: A separate Bank Customer Support (BCS) UI lets authorized bank employees search for transactions by ID, filter by account and date range, and view the full history.
- **Keeps a full audit trail**: Every login attempt (successful or not) and every logout is permanently recorded.

## What it does NOT do

Card issuance, credit limit management, customer onboarding, fraud detection, or currency conversion are outside the scope of this system.

## How it works (overview)

```
Customer / External Service
        │
        │  HTTPS
        ▼
  Transaction API  ──── PostgreSQL database
        │
        ├── National payment   → processed immediately
        ├── International      → queued → external processor
        └── Scheduled payment  → stored → executed automatically later

Bank Staff Browser
        │
        │  HTTPS
        ▼
  Backoffice UI  ──── same Transaction API (read-only views)
```

All traffic is over encrypted HTTPS.

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
| Tests                 | Pytest                                           |
| Infrastructure target | Docker · AWS ECS · AWS RDS                       |

For full architecture decisions, data model, and security design, see the [Technical Design Document](documents/DESIGN_DOCUMENT.md).

## Getting started (local development)

### Prerequisites

- Docker
- `make`
- AWS credentials configured (for SQS)

### Quickstart

```bash
git clone <repo-url>
cd bank-transaction-system
cp .env.example .env           # fill in the required values
make up                        # builds images, starts DB + API
make migrate                   # run Alembic migrations
make seed                      # create the first admin user (needs ADMIN_PASSWORD in .env)
```

API: `http://localhost:8000` — Swagger docs: `http://localhost:8000/docs`

### Available commands

```
make up       — build and start the full stack
make down     — stop containers
make build    — rebuild images without starting
make logs     — follow all logs  (make logs s=api for one service)
make migrate  — run Alembic migrations
make seed     — seed the first admin user
make dev      — DB in Docker + API with hot-reload (needs uv installed locally)
```

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

## Running tests

```bash
cd backend
uv run pytest
```

## Security notes

- `ADMIN_PASSWORD` must be set before running `seed_admin.py` in any non-local environment.
- `INTERNAL_SERVICE_API_KEY` must be a strong random secret (32+ bytes) in production.
