# GAMe v0.3.5 — Trust Graph UI Increment

## Community Edition — Quick Start

GAMe v0.3.5 is a single-company, localhost development
edition for evaluating enterprise AI agent governance, discovery,
runtime observability, and FinOps.

### Installation

Requires Python 3.13.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-connectors.txt
```

### Initialize community accounts

```bash
PYTHONPATH=src python scripts/setup_community.py
```

This automatically creates `data/game.db` and prompts for
individual passwords of at least 15 characters.

| Username | Role |
| --- | --- |
| coadmin | Admin |
| proadmin | Provider Admin |
| bao | Business Owner |

No default passwords or credentials are distributed.

### Start GAMe

```bash
GAME_AUTH_MODE=password PYTHONPATH=src \
python -m uvicorn game.main:app \
--host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000.

### Provider onboarding

Configure your own Microsoft Foundry, AWS, Google, GitHub, or
Atlassian provider connections within GAMe.

Provider subscriptions, credentials, permissions, and any
associated cloud charges are the developer's responsibility.

Azure inventory synchronization is skipped when Microsoft
Foundry is not configured.

### Security

- Localhost development only; not production SaaS.
- The SQLite database is generated locally and excluded from Git.
- Never commit credentials, private keys, database files, or SQL exports.
- Provider Admin and Business Owner start without assigned resources.

---


**Development-only / single-company baseline**, based on the Trust Graph Foundation source. Adds a read-only Trust Graph UI to **Workspace → Trust Graph** and preserves existing RBAC, discovery, and FinOps functions.

The Graph, Inventory, and Evidence tabs are backed by `/api/trust-graph`, `/api/agents`, and `/api/connections`. No sample graph data or live GitHub/Atlassian connectors are bundled.

For setup and use, see `docs/trust-graph-github-atlassian-setup.md`. Keep your local SQLite database and encryption key; do not overwrite them with this source-only ZIP.

# GAMe v0.3.4.2 — Runtime Observability & Financial Access Controls

**Development-only, localhost build**. Built on the restored v0.3.0 architecture plus the single-company RBAC from v0.3.1. No Global/Super Admin portal or multi-company UI.

## macOS startup

1. Back up the existing SQLite database and `~/.config/game/master.key` before applying the Update Only ZIP.
2. Install dependencies in your existing virtual environment:

```bash
source .venv/bin/activate
python -m pip install -r requirements-connectors.txt
```

3. **Once only**, create an initial local company Admin account; the CLI prompts securely for the password:

```bash
PYTHONPATH=src python scripts/create_local_admin.py
```

4. Start with password login enabled:

```bash
GAME_AUTH_MODE=password PYTHONPATH=src python -m uvicorn game.main:app --host 127.0.0.1 --port 8000 --reload
```

5. Open **http://127.0.0.1:8000** and sign in. Initial password change is required. Admins can add the remaining users in **ADMINISTRATION → Admin · Users & Roles**. Every role can change its own password. A local operator can recover a lost sole-Admin password using `scripts/reset_local_admin_password.py`.

**Important:** If you previously exported `GAME_AUTH_MODE=local`, explicitly use `GAME_AUTH_MODE=password` as shown above. The old insecure bypass cannot be enabled accidentally.

## Key docs

- `docs/local-password-login.md` — account bootstrap, login, passwords, security and restrictions.
- `docs/single-company-rbac.md` — role inheritance, provider/agent scoping, existing OIDC API.
- `docs/provider-onboarding.md` — Microsoft, AWS, Google connections.

## Tests

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q
```

No dummy data is seeded. Existing live provider connection records and encrypted credentials are preserved. This is not a production-ready customer-facing SaaS.

## Company branding

An Admin can set the company display name under **Administration → Admin · Users & roles → Company settings**. The sign-in page displays `<company name> Access` and the note **Supported by Happili Platform.** See `docs/company-branding.md`.


### Business Owner approval / Audit Log

From version `0.3.2.2`, approval/rejection is exclusive to a separately assigned **Business Owner**, not the technical Admin. Under **Administration → Users & Roles**, Admin creates a Business Owner; then Admin or scoped Provider Admin assigns them to an agent, submits budget and cost center for approval, and the Business Owner signs in to decide. **Administration → Audit Log** is visible to Admin and Auditor. See [`docs/business-approval-and-audit.md`](docs/business-approval-and-audit.md).

## Advisory Policies and CVE References (v0.3.2.3)

The **Policy checks** screen lists 10 configurable, deterministic advisory rules and records explicit evaluations with evidence and remediation history. No rule automatically modifies remote agents. CVEs can be linked from Agent Details to named components with versions and assessment evidence. The link opens NIST NVD for public CVE/CVSS information; GAMe does not currently import CVSS scores or discover vulnerabilities by itself. See `docs/advisory-policy-and-vulnerability-intelligence.md`.


## Runtime Observability (v0.3.3)

Includes persisted runs/spans, localhost-only authenticated normalized ingestion and a new Runtime observability view. **It does not automatically ingest provider telemetry or raw OTLP yet.** Never insert fictitious run data. See [`docs/runtime-observability.md`](docs/runtime-observability.md) for data contract, collector token, secure testing, scope and limits.

### Azure Foundry Runtime Observability collector (v0.3.3)

The optional read-only Azure Application Insights / Log Analytics collector is in
`scripts/collect_azure_foundry.py`. It is run separately from the GAMe web
server. It requires a workspace ID and **verified exact agent ID mapping**, supports
`--dry-run`, and sends only sanitized metadata to the existing localhost ingestion
endpoint. See [setup and known limitations](docs/azure-foundry-telemetry-collector.md).
No real telemetry is auto-inserted and no live Azure tenant test has been performed.

## v0.3.4.0 FinOps foundation

Agentic FinOps displays observed model tokens and separately classified documented-rate estimates. Azure billed charges are not yet reconciled. See [`docs/agentic-finops.md`](docs/agentic-finops.md).

## v0.3.4.2 Permissions

See `docs/rbac-finops-0342.md` and `docs/sysadmin_coadmin_guide.md`. Local user permissions are editable under Administration → Users & Roles. Server enforcement separates Runtime, token usage, cost estimates, and enterprise Azure ActualCost.

### GitHub and Atlassian Trust Graph provider inventories

See [`docs/github-atlassian-provider-integrations-035.md`](docs/github-atlassian-provider-integrations-035.md) for the provider prerequisites, encrypted local credential setup, UI walkthrough, and known limitations. These are **read-only inventory** adapters, not agent-execution integrations.

### Recover a local account password

If you cannot sign in, an authorized host administrator can reset
an existing local account password without using the web interface.

Stop GAMe and back up its SQLite database before recovery.

**Reset the Admin password:**

    python scripts/reset_local_password.py --username coadmin

**Reset another local account:**

    python scripts/reset_local_password.py --username proadmin

**Use a different database:**

    python scripts/reset_local_password.py --username coadmin --db /path/to/game.db

Passwords are entered through hidden prompts and must contain
15–256 characters. Password hashes use Argon2id.

Successful recovery requires changing the temporary password at next login and revokes existing login sessions while
preserving the account's role and permissions.

Inactive accounts cannot be reactivated by password recovery.

**Security:** Requires authorized filesystem access to the
SQLite database. Intended for local Community Edition installations,
not remote self-service password recovery.


### Docker Compose — localhost evaluation

This alpha build is **not approved for Internet-facing deployment**. The
Compose configuration binds port 8000 to the host loopback interface only,
uses password authentication (not the insecure `local` bypass), and stores
SQLite and the vault key in persistent Docker volumes.

From the repository root:

```sh
docker compose build
docker compose run --rm game python scripts/setup_community.py
docker compose up -d
```

Open http://127.0.0.1:8000. Initialization prompts for locally chosen account
passwords. **Do not** use `docker run -p 8000:8000` or publish this alpha
application to the public Internet. Back up both persistent data and vault
volumes separately; never commit those values. The Docker path must be tested
on a fresh local checkout before using it to evaluate the release.
