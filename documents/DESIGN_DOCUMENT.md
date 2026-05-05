# Bank's Transaction System

## 1. Overview

This document describes the design of an **transaction processing system** for a small, online-first EU-based bank. The system is being built from scratch — no prior implementation exists.

The bank requires two distinct software components:

- A **Transaction Service**: a secure, scalable pure back-end API that creates and processes bank transfers.
- A **Transaction Monitoring UI**: a web interface for the bank's Customer Support team to search and filter transactions.

The system must handle two categories of transfers: **national** (processed immediately within the platform) and **international** (registered as pending and delegated to an external processor). Transactions are immutable; any correction is a new transaction. All records must be retained indefinitely.

## 2. Background

### 2.1 Functional Requirements

| ID    | Requirement                                                                                                                                 |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-01 | The system must process **national transfers synchronously**: validate, deduct balance, and mark as `completed` or `failed` atomically.     |
| FR-02 | **International payments** must be registered as `pending` and handed off to an external service via a message queue.                       |
| FR-03 | Transactions can be **scheduled for a future date/time**, with an execution tolerance of up to **5 minutes**.                               |
| FR-04 | **Debit card** transactions must verify that the account balance is sufficient before approval. If not, the transaction is marked `failed`. |
| FR-05 | **Credit card** transactions are approved without a balance check (handled by an external service).                                         |
| FR-06 | Transactions are **not revertible**. A reversal is a new, independent transaction.                                                          |
| FR-07 | All transaction records must be **stored permanently** (never deleted).                                                                     |
| FR-08 | The **Monitoring UI** must allow searching by Transaction ID and filtering by account number and date range.                                |
| FR-09 | The Monitoring UI must be accessible **only to authorized bank employees** authenticated from their registered work laptops.                |

### 2.2 Non-Functional Requirements

| ID     | Requirement                                                                                                       |
| ------ | ----------------------------------------------------------------------------------------------------------------- |
| NFR-01 | Each login to the Monitoring UI must be recorded in an **audit log table**.                                       |
| NFR-02 | An **archiving strategy** for old transactions must be designed (implementation deferred; planning required now). |
| NFR-03 | All data in transit must be encrypted (**TLS 1.2+**); all data at rest must be encrypted (**AES-256**).           |
| NFR-04 | The Transaction Service must be **horizontally scalable** to absorb unpredictable traffic spikes.                 |

## 3. Proposed Solution

### 3.1 System Architecture

The system is organized into the following layers. Each layer has a single, clearly defined responsibility.

![Bank's Transaction System Architecture](images/Bank's%20Transaction%20System%20-%20Architecture%20Diagram.png)

| Layer                          | Component                                | Responsibility                                                                                                                                                                                                           |
| ------------------------------ | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Customer Bank Support Frontend | Customer Bank Support UI                 | Staff UI for searching and filtering transactions. Hosted as a static site.                                                                                                                                              |
| AuthZ / AuthN                  | Authorization Server                     | Issues tokens after validating user credentials + registered device (IP/MAC).                                                                                                                                            |
| Main Business Logic            | Transaction Service                      | Data validations, balance checks, transaction creation, routing logic, queue publishing. Deployed as stateless containers behind a load balancer — any instance can serve any request, enabling horizontal auto-scaling. |
| Asynchronous Processing        | Message Queue with Preprocessing Worker  | Decouples international payment processing from the main service.                                                                                                                                                        |
| Scheduling Processing          | Scheduling Service with Scheduler Worker | An event is raised when the time is reached and a worker is called.                                                                                                                                                      |
| Main Data                      | Relational Database                      | Primary source of truth. ACID-compliant.                                                                                                                                                                                 |
| Datawarehouse                  | Historical Transactions Table            | Denormalized copy of completed transactions for analytics (Power BI, ML).                                                                                                                                                |
| AI (Future)                    | AI Agent                                 | Natural language interface to generate reports in Markdown format.                                                                                                                                                       |

### 3.2 Authentication & Session Management

Access to the Monitoring UI is handled by the **Transaction Service itself** — there is no external Identity Provider. The bank employee authenticates directly against the backend via a dedicated login endpoint. The flow is the following:

1. The employee opens the Monitoring UI and submits their email and password via `POST /admin/auth/login`.
2. The backend validates the credentials by verifying the password against the bcrypt hash stored in the `users` table.
3. If `registered_ip` is set for that user, the request IP is checked against it. A mismatch immediately rejects the login and records a `login_failed` audit entry.
4. On success:
   - A `login` event is written to the `audit_log` table, recording `user_id`, IP address, and timestamp.
   - Any existing session record for that `user_id` is replaced (enforces single active session per user).
   - A new session record is created in the `sessions` table. The raw token is a cryptographically random opaque string (`secrets.token_urlsafe(32)`); only its **SHA-256 digest** is stored in the database.
   - The raw token and its expiry timestamp are returned to the client in the response body.
5. Every subsequent API request must include the raw token in the `Authorization: Bearer` header.
6. On each request, the backend hashes the incoming token, looks up the matching `sessions` record, and verifies that the session has not expired and that the request IP matches the one recorded at login time.

### 3.3 Transaction Processing

All transaction creation follows a strict **atomic processing model**: a transaction results in either `completed` or `failed` — never a partial state. This is enforced by wrapping every operation in a single database transaction (ACID).

**Processing decision tree:**

```
Transaction received
│
├─ scheduled_for in the future?
│     └─ Persist as SCHEDULED → stop (scheduling engine handles execution)
│
├─ type = INTERNATIONAL?
│     └─ Persist as PENDING → publish to message queue → stop
│
└─ type = NATIONAL
      ├─ method = DEBIT → check balance
      │     ├─ sufficient   → deduct balance + persist as COMPLETED
      │     └─ insufficient → persist as FAILED
      └─ method = CREDIT → persist as COMPLETED immediately
```

**Key invariants:**

- No `UPDATE` or `DELETE` is ever performed on the `transactions` table by a client-facing endpoint.
- Balance deduction and transaction status update are committed in the **same atomic DB transaction**.
- Status transitions (`scheduled` → active, `pending` → `completed/failed`) are performed exclusively by internal service actors (scheduling worker, external processor callback).

### 3.4 International Payments

When a transaction is classified as `type = international`, the flow involves an intermediate **preprocessing worker** that sits between the Transaction Service and the external processor:

1. The Transaction Service persists it as `status = pending`.
2. A message is published to the **International Payment Queue** containing the `transaction_id` and routing metadata.
3. An **internal preprocessing worker** (a dedicated consumer service) listens on the queue. Upon receiving a message, it:
   - Retrieves the full transaction details from the database.
   - Enriches or transforms the payload as required by the external processor's contract (e.g., currency formatting, SWIFT codes, compliance fields).
   - Forwards the prepared request to the **External International Payment Processor** via its API.
4. The external processor, upon completing the payment, notifies the system (via a **callback webhook** or a results queue). The Transaction Service receives this notification and updates the transaction status to `completed` or `failed`.

```
Transaction Service
      │
      │ publish message
      │
      ▼
International Payment Queue
      │
      │ consume
      │
      ▼
Preprocessing Worker (internal)
      │
      │ enrich + forward
      │
      ▼
External Payment Processor
      │
      │ callback / result
      │
      ▼
Transaction Service → update status (completed / failed)
```

The queue provides durability (messages survive processor downtime), natural backpressure, and a Dead-Letter Queue (DLQ) for messages that exhaust retries. The preprocessing worker is the single integration point with the external service, keeping the Transaction Service decoupled from external API details.

### 3.5 Scheduled Transactions

Scheduled transactions are executed by a **CRON-based Lambda worker** triggered every 1 minute by an EventBridge rule (`rate(1 minute)`). The DB is the single source of truth — no external scheduler state is created at transaction registration time.

The Lambda polls the database for due transactions and re-injects each one into the standard processing pipeline (balance check, routing). To prevent double-processing in case of overlapping invocations, it applies an optimistic lock before acting on each row:

```sql
UPDATE transactions
SET    status = 'processing'
WHERE  id = :id AND status = 'scheduled'
AND    scheduled_for <= NOW();
```

Only the invocation that successfully claims the row proceeds. Worst-case execution delay is ~1 minute, well within the 5-minute business tolerance (FR-03).

### 3.6 Data Archival for Analytics (Data Warehouse)

To support analytics (Power BI, Machine Learning) without impacting the operational database, a background archival job periodically (e.g. once per night) copies transactions to a `transaction_history` table. Key design points:

- Dates are **denormalized** (year, month, day, hour stored as separate integer columns) to optimize analytical query performance and partitioning.
- Add user_id and account_id references to enable user-level and account-level analysis without joins to the operational `transactions` table.
- The historical table is append-only and is never used for operational queries or analytical workloads.
- The archival job tracks the last processed `transaction_id` or `created_at` to avoid re-processing.

> _Full implementation is deferred. This section defines the target architecture only._

### 3.7 Audit Logging

Every login attempt, either successful or failed, and logout event is written to the `audit_log` table, recording the following fields: `user_id`, action type, IP address, and timestamp. This is enforced at the authentication layer and persisted regardless of session outcome. The table is append-only and never modified after insertion.

### 3.8 Database Schema

> **Database migrations**: For initial setup, the schema can be applied manually via SQL scripts. For a production-grade approach, **Alembic** (SQLAlchemy's migration tool) is strongly recommended — it tracks schema version history, enables reproducible rollbacks, and is a widely recognised marker of production engineering maturity.

![Bank's Transaction System ERD](images/Bank's%20Transaction%20System%20-%20Entity%20Relation%20Diagram.png)

> **Note:** The ERD diagram shows `mac_address` in the `sessions` table. This column was removed from the implementation — device binding is enforced exclusively via `ip_address`.

#### `users`

| Column        | Type                  | Notes                           |
| ------------- | --------------------- | ------------------------------- |
| id            | UUID                  | PK                              |
| name          | VARCHAR(255)          |                                 |
| national_id   | BIGINT                | UNIQUE                          |
| email         | VARCHAR(255)          | UNIQUE — used as login username |
| phone         | BIGINT                | UNIQUE                          |
| password_hash | VARCHAR(255)          | bcrypt hash                     |
| role          | ENUM(admin, customer) | Drives RBAC                     |
| registered_ip | VARCHAR(45)           | Work laptop IP (supports IPv6)  |
| created_at    | DATETIME              |                                 |
| updated_at    | DATETIME              |                                 |

#### `sessions`

| Column     | Type         | Notes                                                         |
| ---------- | ------------ | ------------------------------------------------------------- |
| id         | UUID         | PK                                                            |
| user_id    | UUID         | FK → users.id, UNIQUE — one active session per user at a time |
| token_hash | VARCHAR(255) | SHA-256 hash of the opaque session token                      |
| ip_address | VARCHAR(45)  | IP used at login time (supports IPv6)                         |
| expires_at | DATETIME     | TTL: created_at + 1 hour                                      |
| created_at | DATETIME     |                                                               |

> The session record is **deleted** on logout or expiry.

#### `audit_log`

| Column     | Type                              | Notes         |
| ---------- | --------------------------------- | ------------- |
| id         | UUID                              | PK            |
| user_id    | UUID                              | FK → users.id |
| action     | ENUM(login, logout, login_failed) |               |
| ip_address | VARCHAR(45)                       |               |
| timestamp  | DATETIME                          |               |

#### `accounts`

| Column     | Type          | Notes                                  |
| ---------- | ------------- | -------------------------------------- |
| id         | UUID          | PK                                     |
| user_id    | UUID          | FK → users.id                          |
| balance    | DECIMAL(19,4) | DECIMAL to avoid floating-point errors |
| created_at | DATETIME      |                                        |

#### `cards`

| Column     | Type                | Notes                      |
| ---------- | ------------------- | -------------------------- |
| id         | UUID                | PK                         |
| account_id | UUID                | FK → accounts.id           |
| card_type  | ENUM(debit, credit) | Drives balance check logic |
| created_at | DATETIME            |                            |

#### `transactions`

| Column              | Type                                        | Notes                                               |
| ------------------- | ------------------------------------------- | --------------------------------------------------- |
| id                  | UUID                                        | PK                                                  |
| source_card         | UUID                                        | FK → cards.id                                       |
| origin_account      | UUID                                        | FK → accounts.id — denormalized for immutable audit |
| destination_account | VARCHAR(255)                                | Internal UUID or external IBAN/SWIFT                |
| amount              | DECIMAL(19,4)                               | CHECK (amount > 0)                                  |
| type                | ENUM(national, international)               |                                                     |
| method              | ENUM(debit, credit)                         | Captured at creation time — immutable               |
| status              | ENUM(pending, completed, failed, scheduled) |                                                     |
| scheduled_for       | DATETIME                                    | NULL unless status = scheduled                      |
| created_at          | DATETIME                                    | Timestamp of record creation                        |

**Key indexes:**

- `(status, scheduled_for)` — scheduling worker poll query
- `(origin_account, created_at DESC)` — transaction history queries
- `(id)` — monitoring search by TxID

#### `transaction_history` _(Data Warehouse — future)_

| Column              | Type          | Notes                                                   |
| ------------------- | ------------- | ------------------------------------------------------- |
| id                  | UUID          | PK                                                      |
| transaction_id      | UUID          | Reference to original — no FK constraint (independence) |
| origin_account_id   | UUID          |                                                         |
| destination_account | VARCHAR(255)  |                                                         |
| amount              | DECIMAL(19,4) |                                                         |
| type                | VARCHAR(20)   |                                                         |
| method              | VARCHAR(10)   |                                                         |
| status              | VARCHAR(20)   |                                                         |
| year                | INT           | Denormalized for partitioning                           |
| month               | INT           |                                                         |
| day                 | INT           |                                                         |
| hour                | INT           |                                                         |
| created_at          | DATETIME      | Original transaction timestamp                          |
| archived_at         | DATETIME      | When this record was copied                             |

### 3.9 Security and Encryption

**Data in Transit**

- All API endpoints enforce **HTTPS (TLS 1.2 minimum)**. HTTP requests are rejected or redirected at the reverse proxy layer.
- The Backoffice SPA is served exclusively over HTTPS via the CDN.
- Session tokens are transmitted only in the `Authorization: Bearer` header over TLS-secured connections — never in URLs or cookies.
- Inter-service communication (Transaction Service → Message Queue, → Database) uses TLS-encrypted connections provided by the managed infrastructure.

**Data at Rest**

- The relational database uses **AES-256 encryption at the storage level**, managed by the cloud provider's key management service (e.g., AWS KMS or equivalent).
- **Daily automated snapshots** of the database are taken during a configured maintenance window. Snapshots are stored independently from the database instance (e.g., in S3) and are encrypted under the same key policy. A retention window of at least 7 days is required. In the event of failure, a new database instance is restored from the most recent snapshot, and Point-in-Time Recovery (PITR) can be used to target any specific moment within the retention period.
- Static frontend assets in object storage are encrypted at rest.

**Key & Secrets Management**

- Encryption keys are managed by a dedicated key management service; no raw keys are stored in application code or environment variables.
- Database credentials, JWT signing secrets, and third-party API keys are injected at runtime from a secrets manager (e.g., AWS Secrets Manager, HashiCorp Vault). They are never hard-coded or committed to version control.

### 3.10 AI Stage — Report Generation Agent _(Future Phase)_

A conversational agent will be added in a future iteration, allowing bank staff to generate transaction reports using natural language. The architecture follows an **agentic LLM pattern**: the model is given a set of tools (skills) it can invoke autonomously to fulfil a request, rather than following a fixed pipeline.

**Communication flow:**

```
Bank Customer Support Frontend
      │
      │ POST /agent/query  { "prompt": "..." }
      │
      ▼
Transaction Service (FastAPI backend)
      │
      │ invoke agent
      │
      ▼
AI Agent (LangChain / LangGraph / pydantic-ai)
      │
      ├─ tool: query_database   → read-only DB replica
      ├─ tool: run_aggregation  → in-context statistical computation
      └─ tool: generate_report  → structured .md output
      │
      │
      ▼
Transaction Service → return report to frontend
```

**Tools (Skills / MCPs):**

| Tool              | Description                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `query_database`  | Exposes a set of **predefined, parameterized Python functions** (e.g., `get_failed_transactions(start_date, end_date)`, `get_transactions_by_account(account_id)`). The agent's role is limited to **extracting parameters from the natural language prompt** and selecting the appropriate function — it never generates or executes dynamic SQL. This prevents SQL injection, uncontrolled query load, and cross-account data exposure. |
| `run_aggregation` | Computes statistical summaries over the retrieved dataset: totals, averages, failure rates, time-series trends.                                                                                                                                                                                                                                                                                                                           |
| `generate_report` | Structures the results into a formatted `.md` file returned to the user for download or inline display.                                                                                                                                                                                                                                                                                                                                   |

**Technology stack:**

- **LangChain / LangGraph** — agent orchestration and tool-calling loop. LangGraph adds support for multi-step, stateful agent workflows (e.g., the agent can ask clarifying questions before querying).
- **pydantic-ai** — strongly-typed tool definitions and structured output validation, ensuring the agent's responses conform to expected schemas before being returned to the frontend.
- Tools can be exposed as **MCP (Model Context Protocol) servers**, making them reusable across future agent implementations.

> _A dedicated follow-up TDD is required before implementation, covering: LLM provider selection, read-only replica access controls, prompt injection mitigations, and tool contract definitions._

## 4. Considered Alternatives

### Authentication Provider

| Option                                                     | Decision       | Rationale                                                                                                                                                                                                                                                                                                             |
| ---------------------------------------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Custom implementation** (bcrypt + opaque session tokens) | ✓ **Selected** | Full control over session lifecycle (IP locking, single-session policy, audit logging). No external dependency. The set of admin users is small and managed internally — no need for self-service registration, MFA, or federated identity.                                                                           |
| **Keycloak** (open-source OAuth 2.0 server)                | ✗ Rejected     | Good option, but requires another self-hosted instance or container, adding infrastructure to operate and maintain. No free-tier benefit over a managed service.                                                                                                                                                      |
| **Managed IdP** (e.g., AWS Cognito, Auth0)                 | ✗ Rejected     | Would add a double-authentication layer: a managed IdP cannot enforce IP locking, single-session-per-user policy, or custom audit logic natively — all of which the system already implements server-side. Adds an external dependency and a JWKS validation round-trip on every request for no net security benefit. |

### Transaction Service Compute

| Option                                                                     | Decision                      | Rationale                                                                                                                    |
| -------------------------------------------------------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Containerized service** (Docker + orchestrator, e.g. **AWS ECS on EC2**) | ✓ **Selected**                | Consistent low latency (no cold starts), portable, horizontally scalable. Suitable for a synchronous API.                    |
| **Serverless functions** (e.g., Lambda)                                    | ✗ Rejected (for main service) | Cold starts introduce latency spikes unsuitable for synchronous transaction endpoints. Acceptable for the scheduling worker. |
| **Virtual Machine**                                                        | ✗ Rejected                    | High operational overhead; inefficient resource utilization under variable load.                                             |

### Async Processing for International Payments

| Option                                     | Decision       | Rationale                                                                                     |
| ------------------------------------------ | -------------- | --------------------------------------------------------------------------------------------- |
| **Message Queue** (RabbitMQ / SQS)         | ✓ **Selected** | Durable, decoupled; supports DLQ; external processor can consume at its own rate.             |
| **Direct HTTP call to external processor** | ✗ Rejected     | Tight coupling; failure in the external service blocks the main request.                      |
| **DB polling by external service**         | ✗ Rejected     | Gives the external service direct DB access, violating encapsulation and security boundaries. |

### Scheduled Transaction Execution

| Option                                                                      | Decision       | Rationale                                                                                                                                                                                                                                                                                                |
| --------------------------------------------------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Event-based scheduler** (e.g., EventBridge Scheduler, Cloud Scheduler)    | ✗ Rejected     | It has several advantages: fires at the exact scheduled time; no polling overhead; scales to any future date. But as the trigger is registered at transaction creation time as a separate call, if that call fails, no event is ever fired and the transaction is silently stuck in `scheduled` forever. |
| **CRON worker + DB polling via Lambda + EventBridge rule (1-min interval)** | ✓ **Selected** | DB is the single source of truth. Simple, cheap, idempotent via optimistic lock. Max latency ~1 min, within the 5-min tolerance. Lambda + EventBridge rule stays within the free tier.                                                                                                                   |
| **Delay Queue** (e.g., SQS Delay)                                           | ✗ Rejected     | Maximum delay capped at 15 minutes — cannot support transactions scheduled days or weeks ahead. Message loss creates inconsistency with DB state.                                                                                                                                                        |

### Database Engine

| Option                                              | Decision       | Rationale                                                                                            |
| --------------------------------------------------- | -------------- | ---------------------------------------------------------------------------------------------------- |
| **Relational DB** (MySQL - PostgreSQL / Amazon RDS) | ✓ **Selected** | Full ACID compliance is non-negotiable for financial data. Mature tooling, strong consistency.       |
| **NoSQL** (MongoDB, DynamoDB)                       | ✗ Rejected     | Eventual consistency models are inappropriate for balance management and financial record integrity. |

### AWS Deployment Stack — Free Tier

The selected cloud provider is **AWS**, operating within the free tier where possible. The table below maps each system component to its AWS service and relevant free-tier constraints.

| Component                                     | AWS Service                                               | Free Tier Notes                                                                                                                                                                                                                                                            |
| --------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Frontend UI (Backoffice SPA)**              | S3 (static hosting) + CloudFront (CDN)                    | S3: 5 GB storage, 20K GET requests/month free. CloudFront: 1 TB data transfer/month free. HTTPS enforced by CloudFront.                                                                                                                                                    |
| **Transaction Service (FastAPI)**             | ECS with EC2 Launch Type — `t3.micro`                     | t3.micro: 750 hours/month free (first 12 months). ECS control plane is free; only the EC2 instance is billed.                                                                                                                                                              |
| **Relational Database**                       | Amazon RDS — PostgreSQL (`db.t3.micro` or `db.t4g.micro`) | 750 hours/month free (first 12 months). **Single-AZ only** — Multi-AZ excluded to remain within free tier.                                                                                                                                                                 |
| **Async Processing — International Payments** | Amazon SQS + AWS Lambda (Preprocessing Worker)            | SQS: 1M requests/month free. Lambda: 1M invocations + 400K GB-s compute/month free.                                                                                                                                                                                        |
| **Scheduling — Future Payments**              | AWS Lambda + EventBridge CRON rule (`rate(1 minute)`)     | One reusable EventBridge rule triggers a Lambda every minute. Lambda polls the DB and processes due `scheduled` transactions.                                                                                                                                              |
| **Nightly Worker — DW + Snapshots**           | AWS Lambda (shared, triggered at 03:00 via EventBridge)   | Same Lambda runtime handles two tasks: (1) copies `completed`/`failed` transactions into `transaction_history` (denormalized); (2) triggers an RDS snapshot and stores it in a private S3 bucket for backup retention. No CSV exports — data is read directly from the DB. |

> All services are deployed in a single AWS EU region (e.g., `eu-west-1`) to satisfy GDPR data residency requirements.

## 5. Appendix

### Sources & References

| Resource                                | URL                                           |
| --------------------------------------- | --------------------------------------------- |
| React Documentation                     | https://react.dev/reference/react             |
| Vite Documentation                      | https://main.vite.dev/                        |
| FastAPI Documentation                   | https://fastapi.tiangolo.com                  |
| SQLAlchemy 2.0 Documentation            | https://docs.sqlalchemy.org                   |
| Alembic (DB migrations)                 | https://alembic.sqlalchemy.org                |
| OAuth 2.0 — RFC 6749                    | https://datatracker.ietf.org/doc/html/rfc6749 |
| Keycloak Documentation                  | https://www.keycloak.org/documentation        |
| JSON Web Token — RFC 7519               | https://datatracker.ietf.org/doc/html/rfc7519 |
| AWS Documentation                       | https://docs.aws.amazon.com/                  |
| Excalidraw                              | https://excalidraw.com                        |
| LucidApp (architecture and DB diagrams) | https://lucid.app/                            |
| PostgreSQL Documentation                | https://www.postgresql.org/docs/              |

_End of Document_
