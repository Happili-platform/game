> **v0.3.3 automatic telemetry mapping:** No per-agent JSON file is required. Use the automatic collector procedure in the final section; earlier `--mapping` instructions are retained only as a legacy reference.

# GAMe — System Administrator & Co-Administrator Operations Guide

**Applies to:** GAMe **v0.3.4.2** (single-company, local development build, including Azure Foundry telemetry collector, runtime enhancements and Popularity/Top N)  
**Audience:** Technical Admins, delegated Provider Admins (CoAdmins), platform operators, security/audit reviewers  
**Document type:** Installation, configuration, operations, recovery and handover runbook  
**Updated:** 2026-11-09 (FinOps foundation; previous runtime and popularity procedures retained)  
**Status:** Operational guide for a **localhost prototype**, **not** a production deployment standard

> **Security boundary:** Run the password-authenticated app on `127.0.0.1`, not a public interface. This application is not yet a commercially hosted multi-company SaaS: browser enterprise SSO/MFA, production database, central key management, strong audit immutability, production monitoring, and disaster recovery are future requirements. No demo data should be seeded into a real environment.

## Contents

1. [System purpose, roles and scope](#1-system-purpose-roles-and-scope)
2. [From v0.1 to the current release](#2-from-v01-to-the-current-release)
3. [System components and data flow](#3-system-components-and-data-flow)
4. [Mac prerequisites and first installation](#4-mac-prerequisites-and-first-installation)
5. [First Admin, company settings and CoAdmin onboarding](#5-first-admin-company-settings-and-coadmin-onboarding)
6. [Provider connection onboarding and discovery](#6-provider-connection-onboarding-and-discovery)
7. [Agent governance and business authorization](#7-agent-governance-and-business-authorization)
8. [Advisory policies, vulnerabilities and audit](#8-advisory-policies-vulnerabilities-and-audit)
9. [Microsoft Foundry runtime telemetry: end to end](#9-microsoft-foundry-runtime-telemetry-end-to-end)
10. [Scheduled telemetry collection](#10-scheduled-telemetry-collection)
11. [Day-2 checks and runbooks](#11-day-2-checks-and-runbooks)
12. [Backup, restore and upgrades](#12-backup-restore-and-upgrades)
13. [Git, GitHub Actions and CI](#13-git-github-actions-and-ci)
14. [Incident triage and troubleshooting](#14-incident-triage-and-troubleshooting)
15. [Security controls and production-readiness gaps](#15-security-controls-and-production-readiness-gaps)
16. [Operational handover checklist and next release](#16-operational-handover-checklist-and-next-release)
17. [Agent popularity, Top N and compatibility troubleshooting](#17-agent-popularity-top-n-and-compatibility-troubleshooting)

---

## 1. System purpose, roles and scope

GAMe is a vendor-neutral **agent inventory, governance, runtime observability and emerging Agentic FinOps** control plane. Its current operational scope is a **single company** and real data only. It discovers supported agents in Microsoft Foundry, AWS AgentCore/Bedrock Agents and Google Agent Engine, tracks agent ownership and approval, evaluates advisory rules, and ingests real execution metadata from Azure Application Insights via a read-only collector.

**Avoid misleading terminology:** "CoAdmin" in this guide is an **operational designation** for an appropriately scoped **Provider Admin**; it is *not* a separate built-in RBAC role. An actual **Admin** retains company-wide technical administration. The **Business Owner** is independent and authorizes business use and spending. Technical Admins **cannot approve or reject** an agent by virtue of their technical role.

| Role | Main duties | Important restrictions |
|---|---|---|
| Admin | Create users, assign roles/scopes, manage providers and company settings, inspect audit records | Cannot make a Business Owner approval/rejection decision |
| Provider Admin (**CoAdmin**) | Manage assigned provider connections, credentials and discoveries, assign Business Owner and submit approval requests within scope | Cannot approve/reject; connection removal may require Admin; no automatic company-wide audit permission |
| User / Agent Owner | Operate or register agents within approved scope, submit business approval requests | Cannot assign broad provider permissions or approve their own work |
| **Business Owner** | Decide on assigned agents' business-justified spend / use | No technical Admin powers; only the *assigned, active* Business Owner can decide; submitter cannot self-approve |
| Auditor | Inspect authorized company-wide activity and audit records | Read-only |
| Viewer | View authorized inventory and findings | Read-only |

The roles above are enforced by backend checks and resource scopes. They are not simply navigation visibility rules. See [single-company-rbac.md](single-company-rbac.md) and [business-approval-and-audit.md](business-approval-and-audit.md).

## 2. From v0.1 to the current release

This is a **functional evolution**, not a claim that every historical prototype was production-ready.

| Release | Introduced / operational consequence |
|---|---|
| v0.1 | FastAPI + SQLite proof of concept, manual inventory, simple advisory rules, recorded usage, Docker support |
| v0.2.x | Provider Connections and real discovery: Microsoft Foundry, AWS AgentCore/Bedrock, Google Agent Engine; credential handling and connection troubleshooting |
| v0.2.4–v0.2.4.1 | Encrypted persistent local provider credentials and Google Agent Engine transport corrections |
| v0.3.0 | Tenant-aware API foundation and renewable workload connection options; current *browser* deployment remains single-company |
| v0.3.1 | Fixed single-company RBAC, Admin / Provider Admin / Agent Owner / Auditor / Viewer, inherited capability model and scopes |
| v0.3.2 | Local username/password sign-in, password management, sessions, Admin users and roles |
| v0.3.2.1 | Configurable company branding and Happili footer |
| v0.3.2.2 | Independent Business Owner approvals, budget/cost-center justification and Administration Audit Log |
| v0.3.2.3 | Ten configurable advisory rules, evaluated finding history, remediation records, manually supported CVE references |
| **v0.3.3** | Persisted runtime runs/spans, dedicated ingestion token, Azure Application Insights collector, collection health/time filters, opt-in Mac scheduler; later agent Popularity/Top N with Happili chart palette |

The abandoned multi-company Super Admin UI is **not** part of the current product. The future v0.3.4 emphasis is **actual usage and Agentic FinOps**, not another agent builder or API gateway. SaaS MCP governance for Atlassian, GitHub, ServiceNow and Salesforce remains on the roadmap.

## 3. System components and data flow

```text
Company Admin / Provider Admin / Business Owner / Auditor
                      |
          Browser on localhost:8000
                      |
           FastAPI application
           |       |       |
       SQLite   AES-GCM   runtime ingest API
       records  keyfile   (loopback + token)
                      ^
                      |
       Azure Foundry collector (separate process)
                      ^
                      |
        Azure Monitor Logs Query API
                      ^
                      |
         Azure Application Insights
                      ^
                      |
       Microsoft Foundry agent executions
```

Provider *discovery* and runtime *telemetry* are different flows. A successful provider connection does not automatically provide execution records. Azure Foundry sends telemetry to **Application Insights / Log Analytics**; the collector queries that service and imports **normalized metadata** to GAMe. The runtime API is **not a raw OTLP ingestion endpoint**.

Operational file layout (default):

| File / directory | Purpose | Backup / security |
|---|---|---|
| `src/game/` | FastAPI backend and DB migration code | Source control |
| `static/` | UI, login, password pages | Source control |
| `scripts/` | Bootstrap, password recovery, telemetry collector and scheduler | Source control |
| `docs/` | Architecture, roadmap and operational guides | Source control |
| `data/game.db` | Real inventory, user, approval, audit and runtime records | **Back up**; do not commit |
| `~/.config/game/master.key` | Local credential-encryption key | **Back up separately**, protect as a secret |
| `~/.config/game/runtime-ingest-token` | Collector ingestion secret | Mode `600`; do not commit or print |
| `~/.config/game/azure-agent-map.json` | Verified source → GAMe agent IDs | Protect and back up; not in Git |
| `~/.config/game/logs/` | Scheduled collector logs | Limit filesystem access and retention |
| `.venv/`, `.git/` | Local environment and Git metadata | Do not distribute in release ZIP |

If `GAME_DB_PATH` or `GAME_VAULT_KEY_PATH` is set, the effective locations may differ from defaults. Check those settings before maintenance or restore.

## 4. Mac prerequisites and first installation

### Required for the current development build

- macOS with Python **3.13** and Python `venv` support. Azure CLI is needed for the **interactive Azure collector authentication path**, but provider discovery with stored credentials does not inherently require it.
- `git`, `sqlite3`, `unzip`; `node` is optional for front-end syntax validation.
- Read access to the chosen Microsoft/AWS/Google resources. For Azure runtime collection, separately obtain access to the **correct Log Analytics workspace**.
- Network access to authorized cloud APIs; no inbound Internet exposure of GAMe.

### Fresh local installation

Use the **current clean full-source** package, not an old initial prototype. The ZIP's top-level folder is `game-mvp/`.

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop
unzip -o ~/Downloads/GAME-v0.3.3-Runtime-Enhancements-Full.zip -d .
cd game-mvp
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt -r requirements-connectors.txt
```

**For an existing installation, use an update ZIP** and preserve `.git/`, `.venv/`, `data/` and `~/.config/game/`. Never overwrite an existing SQLite database with a demo or another user's database.

Check Python imports, versions, and health:

```bash
PYTHONPATH=src python -c 'import game.main; print("Imports OK")'
cat src/VERSION
PYTHONPATH=src python -m pytest -q
```

Create the **first Admin only on an installation that doesn't already have one**:

```bash
PYTHONPATH=src python scripts/create_local_admin.py
```

The script prompts for an initial password and should require a change on first login; no default Admin account is shipped.

### Start the application

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
source .venv/bin/activate
export GAME_RUNTIME_INGEST_TOKEN="$(cat ~/.config/game/runtime-ingest-token)"
GAME_AUTH_MODE=password PYTHONPATH=src \
  python -m uvicorn game.main:app --host 127.0.0.1 --port 8000 --reload
```

**For a brand-new installation without runtime collection yet**, create the collector token first (see §9). Do not create or replace it on an already working collector installation. Open `http://127.0.0.1:8000`, sign in, and verify `http://127.0.0.1:8000/api/health`.

Do not use the legacy insecure local-auth bypass as normal operational login. Do not bind Uvicorn to `0.0.0.0` in this development configuration.

## 5. First Admin, company settings and CoAdmin onboarding

### Admin onboarding

1. Sign in with the initial local Admin and complete the forced password change.
2. Open **Administration → Users & Roles**. Configure the **Company settings** display name for the login page; footer remains `GAMe 0.3.3 · Supported by Happili Platform`.
3. Create a named account for each CoAdmin; choose **Provider Admin**, not Admin, unless unrestricted technical ownership is explicitly required.
4. Restrict Provider Admin scope to the required provider connections and/or agent IDs. A connection grant includes agents in that connection; an agent grant does not grant the whole parent connection.
5. Create separate **Business Owner**, **Auditor**, **Agent Owner** and **Viewer** accounts as required. Avoid shared human accounts.
6. Assign temporary passwords through the Admin UI and require each new user to set their own password. Disable departures immediately.

The effective capability set is inherited by role. Admin ⊇ Provider Admin + Agent Owner + Auditor + Viewer; Provider Admin ⊇ Agent Owner + Viewer; Auditor ⊇ Viewer. Business Owner **does not inherit from Admin**, and technical Admin **does not inherit Business Owner approval rights**.

### Password and account operations

- Each account can change its own password. An Admin can reset another account's password under Users & Roles.
- A lost **sole** Admin password is recovered **locally by a trusted host operator**:

  ```bash
  PYTHONPATH=src python scripts/reset_local_admin_password.py
  ```

- Password reset/change invalidates sessions; disabled accounts lose access. Admin cannot deactivate or demote the last active Admin.
- Use **Administration → Audit Log** to review user changes and credential-related events **without expecting to see passwords or tokens**.

For full implementation notes, see [local-password-login.md](local-password-login.md).

## 6. Provider connection onboarding and discovery

All providers are **customer-owned** resources. Grant the minimum **read-only/list** permissions required for inventory. Provider connection **Test connection** validates credentials/access; **Discover now** reads agent inventory. Neither operation means an agent has business approval or runtime telemetry.

| Provider | Target and auth | First troubleshooting checks |
|---|---|---|
| **Microsoft Foundry** | Project endpoint + Entra tenant/client/secret for legacy local connection, or supported host/shared-app auth modes | Correct project endpoint, tenant ID, secret **value** (not ID), project-scoped read/list authorization; distinguish 401 from 403 |
| **AWS AgentCore** | AWS account/region; temporary IAM Identity Center credentials with session token, host credentials, or cross-account AssumeRole + External ID | `bedrock-agentcore:ListAgentRuntimes`, region, IAM trust, `sts:AssumeRole`, expiry of temporary token |
| **AWS Bedrock Classic** | Separate connector; lists Bedrock agent resources | Check the applicable Bedrock Classic list/read permissions; AgentCore runtime listing is not identical |
| **Google Agent Engine** | Project ID, location, Vertex AI API and ADC/service-account JSON/impersonation | `aiplatform.reasoningEngines.list`, correct project+region, API enabled, OAuth scope/credential validity |
| Private registry | Custom read-only ingestion and scoped credentials | Validate signature/auth, data provenance, exact registry source |

### Routine connection procedure

1. In **Provider Connections**, select provider, specify target endpoint/project/region and approved authentication mode.
2. Enter credentials only via the app's protected form or properly configured workload identity; **never in docs, screenshots, Git or tickets**.
3. **Save**, **Test connection**, then **Discover now**; compare inventory with the provider's authoritative list.
4. Review source IDs and record ownership, approval and cost-telemetry status separately.
5. Re-test after credential rotation or permission changes. For AWS pasted SSO/STS credentials, expect expiry and renew before next discovery; these do **not** refresh automatically.

The local AES-GCM encryption key is stored separately from the SQLite credential ciphertext. Losing that key may make stored secrets unrecoverable. More detail: [provider-onboarding.md](provider-onboarding.md) and [provider-workload-onboarding.md](provider-workload-onboarding.md). Do not apply illustrative AWS trust policies or app registration examples unchanged.

## 7. Agent governance and business authorization

1. Review an automatically discovered or manually registered agent in **Agent Registry**.
2. Technical Admin or scoped CoAdmin assigns the **Business Owner**.
3. An authorized requester submits a business justification, requested monthly budget (USD) and cost center.
4. **Only the active Business Owner explicitly assigned to that agent** can approve or reject the pending request. The submitter cannot approve their own request.
5. Inspect approval state, decision reason, actor and date under the agent and **Audit Log**.
6. Reassignment resets approval as documented. Review significant changes and resubmit when needed.

**Never treat provider metadata such as `approved` or a successful discovery as an GAMe business authorization.** Approval remains an application-side advisory record. It does not automatically stop/start a remote agent or authorize billing in the external enterprise finance system.

When provider cost telemetry is absent, present **Not tracked**, not `$0.00` or proof that a budget was not exceeded. Business Owner-approved monthly budget and actual independently reconciled spending are different data sources.

## 8. Advisory policies, vulnerabilities and audit

The Policy Checks screen provides **10 configurable, deterministic advisory rules** for owner/Business Owner gaps, approval, sensitive access, budget, activity, environment, cost center and **manually reported** affected CVEs. Admin can configure supported rule settings and run evaluations; history includes open/resolved findings and evidence snapshots. Findings are advisory and do not mutate cloud resources.

**Operator workflow:** review configuration → evaluate → assign remediation responsibility → record evidence/notes and due dates → reevaluate to resolve the underlying issue. An explanatory note alone must not hide or resolve a still-present finding.

CVE links require a component, version/digest and evidence for an `affected` assessment. `under_review` is informational. They are **not** automated vulnerability scanning, NVD validation, CVSS enrichment, CISA KEV or EPSS. Never label a general governance issue as a CVE.

**Audit Log** is in Administration for Admin and Auditor. The current browser view shows a bounded recent set of events and is **not** immutable, SIEM-integrated or independently retained. Sensitive operations should be cross-checked with cloud audit logs as needed. See [advisory-policy-and-vulnerability-intelligence.md](advisory-policy-and-vulnerability-intelligence.md) and [business-approval-and-audit.md](business-approval-and-audit.md).

## 9. Microsoft Foundry runtime telemetry: end to end

### A. Source instrumentation and Azure prerequisites

1. In the Microsoft Foundry project, connect **Application Insights** from the agent tracing interface; verify the linked **Log Analytics Workspace**. A workspace may serve multiple agents within the same project.
2. If Azure reports `MissingSubscriptionRegistration` for `Microsoft.OperationalInsights`, register that Azure resource provider in **Subscription → Resource providers** (also ensure `Microsoft.Insights` is registered). This requires sufficient subscription permissions.
3. Execute **each** Foundry agent using a legitimate test invocation. Logs may arrive with delay.
4. Confirm that Azure has records in `AppRequests` and/or `AppDependencies` for the expected time period. Note that the collector currently reads those two tables, **not** every available Application Insights trace table.
5. Record the **Log Analytics Workspace ID** (GUID)—not Application Insights resource name, application ID, instrumentation key or Azure resource ID.
6. Authenticate the collector with `az login` for manual local use, or dedicated read-only Entra app identity with `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`. Ensure workspace query permissions (usually Log Analytics Reader plus any extra permissions for protected tables).

Safe diagnostic KQL in Azure → Application Insights → Logs:

```kusto
union isfuzzy=true AppRequests, AppDependencies
| where TimeGenerated > ago(24h)
| extend FoundryAgentId = tostring(Properties['gen_ai.agent.id']),
         FoundryAgentName = tostring(Properties['gen_ai.agent.name'])
| project TimeGenerated, OperationId, FoundryAgentId, FoundryAgentName, Name
| order by TimeGenerated desc
| take 50
```

This query intentionally excludes prompts and response payloads.

### B. Map Azure identity to GAMe identity

The **left side** is an **observed** Azure agent ID or name from telemetry. The **right side** is the actual `id` in the GAMe `agents` or `discovered_agents` table.

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
sqlite3 -header -column data/game.db \
  "SELECT id, name FROM discovered_agents WHERE name IN ('patient-access-and-scheduling','health-plan-member-services');"
```

In the successful local integration, Azure emitted `patient-access-and-scheduling:1` and the name `patient-access-and-scheduling`. The health-plan agent's own exact ID must be verified from Azure (do not assume its version suffix). The file should have **actual right-hand IDs**, not sample words:

```json
{
  "patient-access-and-scheduling:1": "<actual-GAME-patient-ID>",
  "patient-access-and-scheduling": "<actual-GAME-patient-ID>",
  "<observed-Azure-health-plan-agent-ID>": "<actual-GAME-health-plan-ID>"
}
```

Save as `~/.config/game/azure-agent-map.json` and protect it (`chmod 600`). If the `GAME_DB_PATH` environment override is in use, query that database instead. Ambiguous trace mappings must be **skipped**, not guessed.

### C. Configure the ingestion secret (once)

For a **new** collector installation only:

```bash
mkdir -p ~/.config/game
chmod 700 ~/.config/game
python -c 'import secrets; print(secrets.token_urlsafe(48))' \
  > ~/.config/game/runtime-ingest-token
chmod 600 ~/.config/game/runtime-ingest-token
```

**Do not regenerate the token after successful integration**, unless deliberately rotating it on *both* server and collector. Uvicorn and the collector are different processes and must load the same token.

Start Uvicorn from §4 with that token loaded, then use a **second terminal**:

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
source .venv/bin/activate
export GAME_RUNTIME_INGEST_TOKEN="$(cat ~/.config/game/runtime-ingest-token)"
az login  # only if your Azure CLI session is not already valid
python scripts/collect_azure_foundry.py \
  --workspace 00102aad-d274-4d8f-9eb1-564fdd0d3f9e \
  --mapping "$HOME/.config/game/azure-agent-map.json" \
  --lookback-minutes 1440 --lag-minutes 0 --dry-run
```

The workspace ID above is the ID used in the **local development validation**; replace it for other companies or environments. A 24-hour (`1440` minute) lookback is the collector's currently supported per-run maximum. A nonzero lag can avoid Azure ingestion delay.

**Interpreting real-world tests completed so far:** initial dry runs yielded `0 rows` with a short window; the 24-hour window then retrieved `23 rows / 1 unattributed trace`; after exact ID mapping, `38 rows / 2 trace groups / 2 eligible / 0 unattributed`. The two traces contained 23 and 15 spans respectively. Initial `503` came from missing/invalid server ingest-token configuration; `404` came from mismatched GAMe internal IDs. After correction, **both imports appeared in the Runtime Observability UI**. These values are **historical validation results**, not guaranteed outputs on a new environment.

Once dry run reports eligible records, **remove** `--dry-run` to import actual metadata, then confirm in **Agent runtime observability**. Import again to verify deduplication. Do not ingest invented telemetry to make the dashboard nonempty.

### D. What the dashboard does and does not mean

See [§17](#17-agent-popularity-top-n-and-compatibility-troubleshooting) for the Top N dashboard and related API troubleshooting.

- Switch between **Last 24 hours**, **7 days**, **30 days**, and **All history**; filtering is non-destructive.
- **Historical executions** persist in SQLite when the latest query returns zero rows or a time-filtered view shows zero.
- **Last successful Azure collection** updates on a successful empty query. An unsuccessful collection does not advance that success timestamp.
- `Unknown` runtime status means insufficient source evidence, **not failure**; HTTP result code may indicate request success but is **not proof** that the agent completed its business task.
- `Not tracked` cost means no actual cost evidence. Runtime telemetry alone is not yet the completed Agentic FinOps implementation.

## 10. Scheduled telemetry collection

The current scheduler is a **macOS user `launchd` LaunchAgent**. It queries Azure and posts to the **separately running** GAMe server on `127.0.0.1:8000`. The scheduler installer is **opt-in**, and a user logon, valid Azure identity and running local server remain requirements.

**Important implementation constraint:** The installer `scripts/install_azure_collector_launchd.py` validates `300 <= --interval-seconds <= 86400`. **Five minutes (300 seconds) is the shortest supported scheduled interval in this release.** An earlier suggestion of 1–2 minutes would be rejected by the current installer; do not hand-edit the plist around this guardrail without testing overload, duplicate prevention and Azure query quotas.

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
source .venv/bin/activate
python scripts/install_azure_collector_launchd.py \
  --workspace 00102aad-d274-4d8f-9eb1-564fdd0d3f9e \
  --mapping "$HOME/.config/game/azure-agent-map.json" \
  --interval-seconds 300 \
  --lookback-minutes 60 --lag-minutes 5
launchctl bootstrap gui/$(id -u) \
  "$HOME/Library/LaunchAgents/com.happili.game.azure-foundry-collector.plist"
launchctl kickstart -k \
  gui/$(id -u)/com.happili.game.azure-foundry-collector
```

Inspect status and logs:

```bash
launchctl print gui/$(id -u)/com.happili.game.azure-foundry-collector
plutil -p "$HOME/Library/LaunchAgents/com.happili.game.azure-foundry-collector.plist" | grep StartInterval
tail -n 50 ~/.config/game/logs/azure-collector.stdout.log
tail -n 50 ~/.config/game/logs/azure-collector.stderr.log
```

To change the interval safely, **unload the job**, back up the existing plist, move it out of the way (the installer refuses to overwrite an existing plist), regenerate with the new interval, then bootstrap again:

```bash
PLIST="$HOME/Library/LaunchAgents/com.happili.game.azure-foundry-collector.plist"
launchctl bootout gui/$(id -u) "$PLIST"
cp "$PLIST" "$PLIST.bak"
rm "$PLIST"
# Rerun install_azure_collector_launchd.py with the desired supported interval.
# Then run the launchctl bootstrap and kickstart commands above.
```

**Do not run `rm` unless the preceding `cp` succeeded.** To stop collection, `launchctl bootout ... "$PLIST"`. A running launchd user agent does not imply Azure credentials are renewable or GAMe is running. There is no production cloud scheduler/checkpointing or automatic email alert in this version.

## 11. Day-2 checks and runbooks

| Frequency | Check | Owner | What to do when unhealthy |
|---|---|---|---|
| Each start / upgrade | `src/VERSION`, `/api/health`, sign-in, role gates | Admin | Check logs, imports, DB path, environment variables |
| Daily | Provider connection and inventory freshness | CoAdmin | Test connection, inspect token expiry, run discovery when required |
| Daily | Azure collection's last successful timestamp, scheduler stderr | CoAdmin | Check launchd status, Azure CLI/service principal, workspace RBAC and local server |
| Daily | `unknown` outcomes, missing spans/agent ID mapping | CoAdmin | Compare trace IDs in Azure Logs; fix extraction/mapping only with verified evidence |
| Weekly | Pending Business Owner approvals / budget requests | Admin + Business Owner | Route to assigned Business Owner; technical Admin must not decide |
| Weekly | Advisory findings and overdue remediation | Admin + owners | Reevaluate, attach evidence, prioritize; do not silently clear findings |
| Weekly | Local database + key backups, restore-readiness | Admin | Test a protected copy on an isolated machine; track backup age |
| Per code push | GitHub Actions status and dependencies | Admin / dev maintainer | Fix required dependency files; don't disable failing tests |
| Prior to public hosting | Security release gates | Security / platform | Do **not** expose current prototype publicly |

Suggested acceptance test after a new Azure trace: query Azure → collector dry-run → import → view run and spans → repeat import (no new duplicate) → restart app (record persists) → restrict user permissions and verify agent-scoped visibility.

## 12. Backup, restore and upgrades

### Before any source overlay or schema upgrade

1. Stop Uvicorn and any job importing telemetry (boot out launchd or otherwise quiesce writes).
2. Back up the SQLite DB. For a *running* database, use SQLite's **online backup** rather than blindly copying a live `.db`; the example below assumes the process is stopped.
3. Copy the encryption key **to a separate restricted backup location**, preserving permissions. Back up runtime token and private agent map as separately protected configuration.
4. Record source version, Git commit, installed dependencies, and environment overrides.

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
mkdir -p "$HOME/.config/game/backups"
chmod 700 "$HOME/.config/game/backups"
cp data/game.db "$HOME/.config/game/backups/game-$(date +%Y%m%d-%H%M%S).db"
# Store a separate restricted copy of ~/.config/game/master.key using your approved secure backup method.
cat src/VERSION
git rev-parse --short HEAD 2>/dev/null || true
```

Do not commit any backup, secrets, raw Azure logs, database or mapping files to GitHub. The encryption key is as important as the ciphertext database for restoring provider connections.

### Upgrade process

1. Read release notes and ensure the ZIP is from the current user-approved source baseline (including the GitHub Actions workflow).
2. Extract an **Update** ZIP into the *parent* directory of `game-mvp`, preserving data and local Git history.
3. Activate `.venv`, refresh dependencies from `requirements-dev.txt` and `requirements-connectors.txt` as needed.
4. Check imports and run tests, restart Uvicorn, and test login, discovery, policy, business approval, audit, historical runtime records, and live collector import.
5. Re-enable launchd and check first successful run only after the app is healthy.

Rollback caution: schema changes may be additive but rolling back **source only** is not always safe after migrations. Restore a **consistent source+DB+master-key backup**, or validate backward compatibility before downgrading. Never overwrite a newer live DB with an old ZIP's data folder.

## 13. Git, GitHub Actions and CI

The latest shared source package includes `.github/workflows/python-app.yml` for Python **3.13**, flake8 and pytest. An observed GitHub Actions failure was:

```text
ModuleNotFoundError: No module named 'boto3'
1 failed, 85 passed
```

This was a **CI dependency installation gap**: the workflow in the available v0.3.3 source installs `requirements.txt`, but the AWS connector optional dependencies, including `boto3`, are declared in `requirements-connectors.txt`. The workflow in the inspected package has **not** yet incorporated the suggested fix. The next maintainer action is to amend the dependency installation step and verify GitHub-hosted CI:

```yaml
- name: Install dependencies
  run: |
    python -m pip install --upgrade pip
    python -m pip install flake8
    python -m pip install -r requirements-dev.txt
    python -m pip install -r requirements-connectors.txt
```

Do not assume local passing tests prove the GitHub Actions environment is correctly configured. Verify the actual workflow after the next push.

For commit attribution, set **repository-local** Git identity using a verified email from the intended GitHub account. The Git author/committer identity is separate from `gh auth`/SSH account authentication:

```bash
git config --local user.name "YOUR_GITHUB_USERNAME"
git config --local user.email "YOUR_VERIFIED_GITHUB_EMAIL"
git var GIT_AUTHOR_IDENT
git var GIT_COMMITTER_IDENT
gh auth status
```

Never put live credentials in CI logs, repository secrets without policy review, tracked configuration files, or ZIP releases.

## 14. Incident triage and troubleshooting

| Symptom | Likely cause | Safe next action |
|---|---|---|
| Application fails with missing `game.core` or another import | Incomplete source overlay | Restore a **full source** patch matching the release; verify `PYTHONPATH=src` and imports; don't touch DB |
| `ModuleNotFoundError: boto3` on Actions | Connector requirements not installed in workflow | Install `requirements-connectors.txt` in CI and rerun tests |
| Foundry Application Insights creation fails `MissingSubscriptionRegistration` | Azure `Microsoft.OperationalInsights` not registered | Subscription admin registers provider; verify `Microsoft.Insights` too |
| Azure dry run `0 metadata rows` | No recent relevant records, wrong workspace, time window or query/table mismatch | Inspect Azure Logs/Foundry traces, workspace ID; try supported 24h dry run |
| Rows found, `unattributed` traces | Placeholder or nonmatching Azure ID map, missing agent identity attributes | Inspect `gen_ai.agent.id`/`.name`; replace map keys with **observed** exact values |
| Collector import **503** | Ingestion token not configured/too short **on the running server** | Start server with same valid 32+ character token as collector; restart Uvicorn |
| Collector import **404** | GAMe ID on map right-hand side not found | Query actual `agents`/`discovered_agents.id`; ensure server DB matches target DB |
| Collector import **401/403** | Invalid auth or insufficient permissions | Verify token/Azure identity, workspace RBAC; do not widen IAM blindly |
| Collector reports duplicate/replay | Expected overlapping windows with same run identity | Confirm replay count and stable unique historical runs |
| Current period shows zero while All history shows data | Date filter; no recent new executions | Confirm historical totals persist; inspect Last Successful Azure Collection |
| `Unknown` status | No reliable overall agent outcome in source | Inspect actual request `Success`/`ResultCode`; don't infer success from tool subspans |
| Scheduled collection not updating | launchd not loaded, Azure login expired, server stopped or local secret permissions wrong | `launchctl print`, stdout/stderr logs, token file `chmod 600`, verify local server |
| Cannot decrypt provider credentials after moving machines | Missing/wrong AES master key | Restore the matching key from approved backup; never regenerate over ciphertext |
| DB upgrade or reset appears to lose agents | Wrong `GAME_DB_PATH` or replaced DB | Stop, inspect effective DB path, restore consistent protected backup |
| Runtime UI JavaScript error on `runtimeTopN` | New JS paired with old HTML | Deploy matching HTML/JS/CSS, refresh browser |
| Runtime popularity panel `Not Found` / 404 | Missing route on running backend or mismatched deployment | Check OpenAPI and server checkout per §17 |
| `_IncludedRouter` lacks `path` in a route inspection | Inspection script assumed all `app.routes` objects expose `.path` | Use OpenAPI inspection in §17 |

For cloud query troubleshooting, prefer **metadata-only** exports (table names, property keys, trace IDs, agent IDs). Never paste prompt contents, tool inputs/outputs, private tokens or credentials into tickets or shared AI chats.

## 15. Security controls and production-readiness gaps

**Currently implemented for local prototype:** Argon2id local passwords, session/CSRF controls, role and scope authorization, separately encrypted local provider credentials, local application audit history, localhost-only collector secret, read-only Azure Logs querying, duplicate protection, sanitized runtime metadata, and no automatic cloud-side remediation.

**Still required before hosted SaaS:** enterprise browser SSO/MFA and lifecycle provisioning, managed tenant-isolated secrets, production database and migration strategy, effective tenant isolation and security testing, reliable background workers/checkpointing, safe egress, telemetry quotas/rate limiting, central audit export and retention, monitoring/alerting, robust backup/restore, disaster recovery, privacy/data residency, and a support operating model. See [security-gaps.md](security-gaps.md).

The telemetry ingestion token is a **single local company-wide collector secret**, not per-collector identities. Changing the local token without coordinated rotation breaks ingestion. The current scheduler is not a cloud service. No automatic CVSS verification, agent cost reconciliation, production MCP governance, or agentic ROI calculation exists yet.

## 16. Operational handover checklist and next release

Before transferring platform operation to another Admin or CoAdmin, verify:

- [ ] Source commit and `src/VERSION` recorded; correct branch and GitHub Actions workflow identified.
- [ ] Named active Admin, scoped Provider Admin(s), and independently assigned Business Owner(s) exist.
- [ ] Company branding and correct footer confirmed.
- [ ] Provider targets/regions/roles and renewable/static credential modes documented **without copying secrets**.
- [ ] SQLite DB, master key, collector token and Azure mapping protected and recoverable through approved backup processes.
- [ ] Both Microsoft Foundry agents appear in Registry and have correct external↔internal ID mapping.
- [ ] Azure workspace, permission scope, tracing setup and collector identity are documented.
- [ ] Dry-run attribution reports eligible traces; live import is visible; replay creates no duplicates.
- [ ] Last successful collection and scheduled collector logs are checked; unknown status and Not tracked cost are understood.
- [ ] For Popularity/Top N deployment, verify registered API, chart, Happili colors and retained All history runs.
- [ ] Technical Admin cannot approve/reject; assigned Business Owner can; Audit Log records the decision.
- [ ] Policy evaluation, remediation records and CVE-reference caveats reviewed.
- [ ] Restoring a protected backup and resetting sole-Admin password have written procedures.
- [ ] Open CI dependency issue (`boto3`/connector requirements) is resolved in the actual GitHub workflow and confirmed by a passing run.
- [ ] Production gaps are listed and accepted as blocking for Internet exposure.

### Next milestone: v0.3.4 Agentic FinOps

Continue with real provider usage/billing collection, attribution to agent executions, verified token/model and tool costs, cost-center/budget reconciliation, and distinctions between actual cost, estimate, and **Not tracked**. Do not derive spend from the mere existence of a span. This is a new capability milestone; it is **not** complete in v0.3.3.

### Related documentation

- [architecture.md](architecture.md) — overall design and data flows
- [product_roadmap.md](product_roadmap.md) — agreed release sequence and acceptance goals
- [provider-onboarding.md](provider-onboarding.md) and [provider-workload-onboarding.md](provider-workload-onboarding.md)
- [single-company-rbac.md](single-company-rbac.md), [local-password-login.md](local-password-login.md)
- [business-approval-and-audit.md](business-approval-and-audit.md)
- [advisory-policy-and-vulnerability-intelligence.md](advisory-policy-and-vulnerability-intelligence.md)
- [runtime-observability.md](runtime-observability.md), [azure-foundry-telemetry-collector.md](azure-foundry-telemetry-collector.md), [runtime-observability-enhancements.md](runtime-observability-enhancements.md)
- [security-gaps.md](security-gaps.md)


---

## 17. Agent popularity, Top N and compatibility troubleshooting

**Scope:** v0.3.3 Popularity/Top N enhancement, following the stable Runtime Enhancements + SysAdmin/CoAdmin Guide baseline. This is a **UI and aggregate API** increment: it does not change Azure telemetry collection, stored execution retention, or financial attribution. A particular installation is **not** considered validated until the verification below succeeds on that installation.

### A. Operational view

- **Most used agents:** ranked by *recorded execution count*, showing each agent's count and share of the matching recorded runs.
- **Top N selector:** Top 5 (default), Top 10, or Top 20. Remaining agents are combined in **Others**, so hundreds of agent series never crowd the chart.
- **Daily executions:** stacked bars by active UTC date; show the total number of runs per day and individual Top N agent contributions. Hover for the agent, day and run count.
- **Find agent:** filters the ranking/chart by name or internal ID, without silently changing the global summary metric tiles. Selecting a ranked agent filters execution history.
- **Period filter:** Last 24 hours, 7 days, 30 days and All history. Date filtering never deletes stored executions.
- **All history with long timelines:** displays the latest 60 active days in the chart, while ranking totals cover the entire selected period.
- **Happili theme:** `static/style.css` defines `--runtime-series-01` through `--runtime-series-20` and `--runtime-series-others`. Blue, orange, green, teal, lime and yellow are brand colors; **Others** uses neutral slate gray.

**Terminology:** An agent with more recorded runs is *more frequently executed*, not necessarily used by more people. A run with 23 spans counts **one run**, not 23. Unknown outcomes and costs remain **Unknown** and **Not tracked**.

### B. Release compatibility rule

Previous partial updates caused two distinct faults: the frontend expected `#runtimeTopN` but the installed HTML lacked it; after the HTML was corrected, the popularity API returned `Not Found` because backend and frontend versions were mismatched.

Deploy these files from **the same validated release** as one compatible set:

```text
src/game/runtime.py
static/index.html
static/app.js
static/style.css
```

Do not overlay older hotfix ZIPs on top of the current GitHub clone. Before updating, stop Uvicorn and the local collector; record the Git commit, check `git status --short`, and make a protected copy of `data/game.db`. Keep `~/.config/game/master.key`, `runtime-ingest-token` and `azure-agent-map.json` untouched. Compare changes against your working checkout, including your GitHub Actions updates.

Example preflight for the **v0.3.3-Popularity-TopN-Stable-Update** package:

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
git status --short
git rev-parse --short HEAD
mkdir -p ../game-safety-backup
cp data/game.db ../game-safety-backup/game.db.pre-topn

mkdir -p /tmp/game-topn-review
unzip -l ~/Downloads/GAME-v0.3.3-Popularity-TopN-Stable-Update.zip
unzip -o ~/Downloads/GAME-v0.3.3-Popularity-TopN-Stable-Update.zip \
  -d /tmp/game-topn-review

diff -u static/index.html /tmp/game-topn-review/game-mvp/static/index.html || true
diff -u src/game/runtime.py /tmp/game-topn-review/game-mvp/src/game/runtime.py || true
```

If those changes are approved, deploy the matching four application files together, run the application's tests and restart Uvicorn. Package overlays must never replace a live database or master key. A documentation-only upgrade does not require a server restart.

### C. Verify the route correctly

In this source, `src/game/runtime.py` defines `@router.get('/popularity')`. The full endpoint is expected to be `GET /api/runtime/popularity`, but a function existing in the file **does not prove** the running server exposes it.

Check the OpenAPI schema from the project root with `.venv` active:

```bash
PYTHONPATH=src python - <<'PYCODE'
from game.main import app
for path, methods in app.openapi().get('paths', {}).items():
    if 'popularity' in path:
        print('Registered:', path, 'methods:', ', '.join(methods))
PYCODE
```

Expected:

```text
Registered: /api/runtime/popularity methods: get
```

**Why the earlier route diagnostic crashed:** This app may contain `_IncludedRouter` entries in `app.routes` that have no `.path`. Do not use `r.path` before verifying the attribute. The safe alternative is:

```bash
PYTHONPATH=src python -c \
"from game.main import app; print([r.path for r in app.routes if 'popularity' in getattr(r, 'path', '')])"
```

Prefer the OpenAPI check. If no matching path is returned, inspect `main.py` router inclusion, which code checkout is imported, and your release contents **before** reapplying updates. Once registered, restart the actual serving process—an old Uvicorn process on port `8000` can still return 404 even when a newly inspected source tree contains the route.

### D. Validate the browser and runtime data

1. Sign in to `http://127.0.0.1:8000` and verify the running API: in a logged-in browser session, open `/api/runtime/popularity?period=all&top_n=5`. A healthy authorized response is **HTTP 200** with JSON including `ranking`, `daily`, `others_runs`, `scope_total_runs` and `coverage`. Without session authorization, a redirect/401/403 is possible and is different from a missing route.
2. Hard refresh using `Cmd + Shift + R` after installing compatible HTML, JavaScript and CSS.
3. Open **Agent runtime observability**, select **All history**, and verify imported executions for `patient-access-and-scheduling` and `health-plan-member-services` remain available.
4. Switch Top 5 / Top 10 / Top 20, test Find agent, then click a ranked agent. Counts must correspond to recorded **runs**, not span counts.
5. Inspect the Happili color series; if only two agents have executions, two distinct series should appear when the period and filters include their runs.
6. Recheck collector health and the Azure collector dry run only if new executions fail to arrive. Re-running the collector with an overlapping window should not create duplicate historical records.

### E. Troubleshooting matrix

| Symptom | Likely cause | Safe action |
|---|---|---|
| `null is not an object` referencing `runtimeTopN` | Old `index.html`, newer `app.js` | Install matching frontend files and hard refresh |
| Popularity panel displays `Not Found` or a 404 | Running backend lacks `/api/runtime/popularity`, incorrect application checkout or stale server process | Inspect OpenAPI, restart correct server and verify authenticated GET |
| Python verification throws `_IncludedRouter` `AttributeError` | Route-inspection code assumed all routes have `.path` | Use `app.openapi()` diagnostic above |
| Popularity endpoint responds 401/403 | Authentication or `runtime.view` scope | Sign in, inspect role/scopes; do not disable RBAC |
| New chart shows no executions | Selected period/search has no matching runs | Select All history, clear search; compare history and collection health |
| Chart totals differ from Azure span count | One run contains multiple spans | Compare to `runtime_runs`, not `runtime_spans` |
| Several agents shown under Others | Expected Top N grouping | Increase Top N or search a specific agent |
| Chart displays old colors | Stale assets or missing CSS variables | Check `static/style.css` and browser cache |
| Search ranking count differs from global cards | Search only filters the popularity view | Use `scope_total_runs` versus the matching count appropriately |
| No recent Azure runs but old entries remain | No new telemetry or collector outage | Check last successful collection and scheduler logs; retained records should not disappear |

### F. Release gate before v0.3.4

- [ ] GitHub source commit and four-file compatibility set are recorded.
- [ ] OpenAPI includes `/api/runtime/popularity`; authenticated GET responds 200.
- [ ] No `runtimeTopN` JS error and no `Not Found` popularity view.
- [ ] Both known Foundry agents' imported runs are accessible under All history.
- [ ] Top N, Others, search, stacked daily bars and distinct Happili colors work on Mac.
- [ ] Collector, collection-health reporting, historical persistence and deduplication still work.
- [ ] Backend regression suite, JS syntax and GitHub Actions pass on the actual current branch.

**Verification status:** Package-level tests passed during development; the restored GitHub installation still requires a successful on-device browser/API check. Do not declare runtime UI acceptance solely from the presence of a Python function.

Related detail: [runtime-agent-popularity.md](runtime-agent-popularity.md).


## v0.3.3 — Automatic Foundry discovery and telemetry identity matching

**No per-agent JSON mapping is required.** After a Microsoft Foundry provider connection is configured with valid read-only discovery credentials, the scheduled collector now calls `POST /api/runtime/azure-inventory-sync` on the localhost GAMe server using its existing runtime ingestion token. GAMe refreshes the inventory from every connected Foundry project, persists new discovered agents, and provides their IDs to the collector. The collector resolves `gen_ai.agent.id`, `gen_ai.agent.name` and other allowlisted identity attributes against the synchronized inventory.

* New agents are discovered at each successful collector poll; their telemetry is attributed only after a unique identity match. No change to `~/.config/game/azure-agent-map.json` is required.
* Duplicate agent names across projects **cannot be resolved from name-only telemetry**. These runs are skipped rather than attributed to the wrong project. A trace carrying a unique provider identifier can still match. An agent with no reliable identifying trace properties remains unattributed.
* This does **not** create new Azure provider connections or grant permissions automatically. A valid connection and credentials must already be configured once for each Foundry project. Business Owner approval remains separate.
* Auto-discovery requires the running GAMe process to have access to existing encrypted/Entra workload credentials. If discovery fails, the collector reports a failure rather than inventing mappings.
* The previous `--mapping` option remains available for exceptional legacy use, but it bypasses automatic inventory sync. Do not pass it in normal operation.

**Manual dry run (without a mapping file):**

```bash
export GAME_RUNTIME_INGEST_TOKEN="$(cat ~/.config/game/runtime-ingest-token)"
python scripts/collect_azure_foundry.py \
  --workspace 00102aad-d274-4d8f-9eb1-564fdd0d3f9e \
  --lookback-minutes 60 --lag-minutes 5 --dry-run
```

**Scheduled collector:** stop the old macOS job, remove the old plist, then regenerate without `--mapping`:

```bash
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.happili.game.azure-foundry-collector.plist" || true
mv "$HOME/Library/LaunchAgents/com.happili.game.azure-foundry-collector.plist" "$HOME/Library/LaunchAgents/com.happili.game.azure-foundry-collector.plist.old"
python scripts/install_azure_collector_launchd.py \
  --workspace 00102aad-d274-4d8f-9eb1-564fdd0d3f9e \
  --interval-seconds 300 --lookback-minutes 60 --lag-minutes 5
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.happili.game.azure-foundry-collector.plist"
launchctl kickstart -k gui/$(id -u)/com.happili.game.azure-foundry-collector
```

Previously ingested telemetry remains in SQLite. No new agent executions are invented or seeded. In the event of ambiguous/missing attributes, examine the collector diagnostics and upstream Azure metadata rather than changing identities by guesswork.


## 18. v0.3.4.0 FinOps Operations

For FinOps initialization and collector checks, see [`agentic-finops.md`](agentic-finops.md). The existing Azure collector now submits token evidence from supported model spans; no extra secret is required. Preserve the localhost collector token and master key. Admin may record documented estimate rates; Business Owner remains the exclusive business spending approver. A blank FinOps dashboard means no observed model token spans have been imported—not necessarily no agent executions. Re-run the collector with `--dry-run` and check the `Observed model usage operations` count. Missing costs remain **Not tracked**, and zero Azure records never delete historical usage.

## 19. v0.3.4.1 — Azure Cost Management scope-cost collection

The resource-cost collector is a **separate manual command** from the scheduled Foundry runtime collector. It does not affect the latter's five-minute schedule or SQLite historical runtime records.

1. Ensure GAMe is running with the existing local collector credential.
2. Use `az login` with a Cost Management read-only identity scoped to your subscription or Foundry resource group.
3. Follow `docs/agentic-finops.md` to run `scripts/collect_azure_costs.py --scope ... --days 7 --dry-run`.
4. Inspect the scope and resource totals, then rerun without `--dry-run` with the shared `GAME_RUNTIME_INGEST_TOKEN` loaded.
5. Visit **Agentic FinOps → Azure resource-scope charges**. The charges must remain separate from agent-level cost estimates and Business Owner budgets.
6. Run a second import and confirm record counts do not double. An empty subsequent query does not remove historical records.

Azure resource scope costs may include costs unrelated to your two agents. This is **not** agent-level cost allocation or a final invoice verification. No new permissions to approve spending are given to Admin or Provider Admin.

## 20. v0.3.4.2 — Edit user permissions and financial access

As Admin, open **Administration → Users & roles**, select **Edit** on an existing local user, choose the primary role and review the automatically checked inherited capabilities. Check a higher capability to select its prerequisites automatically; deselecting a prerequisite removes the dependent permissions. Save; the API applies changes to existing sessions immediately. The server refuses permissions beyond the primary role ceiling. Admin cannot grant itself Business Owner approval or remove its mandatory user-administration capability.

`runtime.view` governs runs, trace/span details and popularity. `finops.usage.view` governs token usage, `finops.estimates.view` governs rates and budgets, and `finops.billing.view` governs full Azure resource ActualCost. Only Admin/Auditor preset roles include enterprise billing. Provider Admin/Agent Owner permissions follow their selected agent/provider scopes. Business Owner sees only explicitly assigned agents. Viewer has no detailed runtime or FinOps access by default.

Back up `data/game.db` before upgrading and keep `~/.config/game/master.key` and `runtime-ingest-token` unchanged. Audit Log captures user access changes and rate-card creation. The current customization editor applies to local password users; OIDC users use role/scope presets.
