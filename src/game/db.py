# SPDX-License-Identifier: AGPL-3.0-only
"""SQLite prototype schema with explicit tenant isolation and idempotent legacy migration."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .policy_engine import DEFAULT_RULES


def db_path() -> Path:
    return Path(os.getenv("GAME_DB_PATH", "data/game.db"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def connection():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=15)
    # Local-only prototype: prevent other OS users from reading the database file.
    if os.name == 'posix':
        path.chmod(0o600)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize() -> None:
    with connection() as db:
        from .trust_graph import initialize as initialize_trust_graph
        initialize_trust_graph(db)
        from .provider_integrations import initialize as initialize_provider_inventory
        initialize_provider_inventory(db)
        db.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          provider TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          owner_email TEXT,
          environment TEXT NOT NULL CHECK(environment IN ('development','staging','production')),
          approval_status TEXT NOT NULL CHECK(approval_status IN ('approved','pending','unapproved')),
          lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('active','paused','retired')),
          cost_center TEXT NOT NULL DEFAULT '',
          budget_usd REAL NOT NULL DEFAULT 0 CHECK(budget_usd >= 0),
          sensitive_access INTEGER NOT NULL DEFAULT 0,
          last_seen TEXT,
          source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual','demo')),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage_events (
          id TEXT PRIMARY KEY,
          agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
          occurred_at TEXT NOT NULL,
          cost_usd REAL NOT NULL CHECK(cost_usd >= 0),
          input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
          output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
          outcome TEXT NOT NULL CHECK(outcome IN ('success','failure','unknown')),
          source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual','demo'))
        );
        CREATE INDEX IF NOT EXISTS idx_usage_agent_time ON usage_events(agent_id,occurred_at);
        """)
        db.executescript("""
        CREATE TABLE IF NOT EXISTS provider_connections (
          id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          label TEXT NOT NULL,
          scope_json TEXT NOT NULL,
          env_prefix TEXT NOT NULL,
          created_at TEXT NOT NULL,
          last_synced_at TEXT,
          last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS discovered_agents (
          id TEXT PRIMARY KEY,
          connection_id TEXT NOT NULL REFERENCES provider_connections(id) ON DELETE RESTRICT,
          external_id TEXT NOT NULL,
          name TEXT NOT NULL,
          provider TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          provider_status TEXT NOT NULL DEFAULT 'unknown',
          owner_email TEXT,
          environment TEXT NOT NULL DEFAULT 'unknown',
          approval_status TEXT NOT NULL DEFAULT 'unknown',
          lifecycle_status TEXT NOT NULL DEFAULT 'unknown',
          cost_center TEXT NOT NULL DEFAULT '',
          budget_usd REAL NOT NULL DEFAULT 0,
          sensitive_access INTEGER NOT NULL DEFAULT 0,
          last_seen TEXT,
          discovered_at TEXT NOT NULL,
          discovery_last_seen TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'discovered',
          created_at TEXT NOT NULL,
          UNIQUE(connection_id, external_id)
        );
        CREATE INDEX IF NOT EXISTS idx_discovered_connection ON discovered_agents(connection_id);
        """)
        db.executescript("""
        CREATE TABLE IF NOT EXISTS provider_credentials (
          connection_id TEXT PRIMARY KEY REFERENCES provider_connections(id) ON DELETE CASCADE,
          encrypted_json TEXT NOT NULL,
          saved_at TEXT NOT NULL,
          rotated_at TEXT NOT NULL,
          expires_at TEXT
        );
        """)
        # Upgrade existing v0.2.x rows in-place, rather than replacing the user's database.
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tenants (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tenant_memberships (
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          issuer TEXT NOT NULL, subject TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('viewer','analyst','connection_admin','tenant_admin')),
          active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
          PRIMARY KEY (tenant_id,issuer,subject)
        );
        CREATE TABLE IF NOT EXISTS audit_events (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id),
          actor TEXT NOT NULL, operation TEXT NOT NULL,
          resource_id TEXT NOT NULL,
          occurred_at TEXT NOT NULL
        );
        """)
        db.execute("INSERT OR IGNORE INTO tenants(id,name,created_at) VALUES (?,?,?)",
                   ('local-dev', 'Legacy / Local Development', iso(utc_now())))
        # Single-company branding: convert only the unchanged legacy placeholder.
        # Custom company names persist across upgrades and restarts.
        db.execute("UPDATE tenants SET name='Company' WHERE id='local-dev' AND name='Legacy / Local Development'")
        # Defaults exist only for upgrading records from the old single-user installation.
        for table in ('agents','usage_events','provider_connections','discovered_agents','provider_credentials'):
            columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
            if 'tenant_id' not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'local-dev'")
        columns = {row['name'] for row in db.execute('PRAGMA table_info(provider_connections)')}
        if 'auth_mode' not in columns:
            db.execute("ALTER TABLE provider_connections ADD COLUMN auth_mode TEXT NOT NULL DEFAULT 'legacy'")
        if 'auth_config_json' not in columns:
            db.execute("ALTER TABLE provider_connections ADD COLUMN auth_config_json TEXT NOT NULL DEFAULT '{}'")
        for table in ('agents','usage_events','provider_connections','discovered_agents','provider_credentials'):
            db.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_tenant ON {table}(tenant_id)')
        # Single-company RBAC migration: preserve existing users and roles, without rebuilding the database.
        schema_row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tenant_memberships'").fetchone()
        if schema_row and "'agent_owner'" not in (schema_row['sql'] or ''):
            db.execute("ALTER TABLE tenant_memberships RENAME TO tenant_memberships_v030_backup")
            db.execute("""CREATE TABLE tenant_memberships (
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                issuer TEXT NOT NULL, subject TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN
                    ('viewer','analyst','connection_admin','tenant_admin','agent_owner','provider_admin','business_owner','auditor','admin')),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                scope_json TEXT NOT NULL DEFAULT '{"kind":"all"}',
                PRIMARY KEY (tenant_id,issuer,subject))""")
            db.execute("""INSERT INTO tenant_memberships (tenant_id,issuer,subject,role,active)
                SELECT tenant_id,issuer,subject,role,active FROM tenant_memberships_v030_backup""")
            db.execute("DROP TABLE tenant_memberships_v030_backup")
        columns = {r['name'] for r in db.execute('PRAGMA table_info(tenant_memberships)')}
        if 'scope_json' not in columns:
            db.execute("ALTER TABLE tenant_memberships ADD COLUMN scope_json TEXT NOT NULL DEFAULT '{\"kind\":\"all\"}'")
        columns = {r['name'] for r in db.execute('PRAGMA table_info(agents)')}
        if 'connection_id' not in columns:
            db.execute('ALTER TABLE agents ADD COLUMN connection_id TEXT')
        # Add Business Owner to existing OIDC memberships without invalidating existing memberships.
        role_schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tenant_memberships'").fetchone()
        if role_schema and "'business_owner'" not in role_schema['sql']:
            db.executescript("""
            CREATE TABLE tenant_memberships_role_new (
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                issuer TEXT NOT NULL, subject TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('viewer','analyst','connection_admin','tenant_admin',
                  'agent_owner','provider_admin','business_owner','auditor','admin')),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                scope_json TEXT NOT NULL DEFAULT '{"kind":"all"}',
                PRIMARY KEY(tenant_id,issuer,subject));
            INSERT INTO tenant_memberships_role_new(tenant_id,issuer,subject,role,active,scope_json)
              SELECT tenant_id,issuer,subject,role,active,scope_json FROM tenant_memberships;
            DROP TABLE tenant_memberships;
            ALTER TABLE tenant_memberships_role_new RENAME TO tenant_memberships;
            """)
        # No demo seeding in single-company releases. New databases start empty.

        # v0.3.2: local password accounts are separate from OIDC memberships.
        db.executescript("""
        CREATE TABLE IF NOT EXISTS local_users (
          id TEXT PRIMARY KEY,
          username TEXT NOT NULL UNIQUE COLLATE NOCASE,
          display_name TEXT NOT NULL DEFAULT '',
          email TEXT NOT NULL DEFAULT '',
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin','provider_admin','agent_owner','business_owner','auditor','viewer')),
          scope_json TEXT NOT NULL DEFAULT '{"kind":"all"}',
          active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
          must_change_password INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL, password_changed_at TEXT, last_login_at TEXT
        );
        CREATE TABLE IF NOT EXISTS local_sessions (
          token_hash TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES local_users(id) ON DELETE CASCADE,
          csrf_token TEXT NOT NULL,
          created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          expires_at TEXT NOT NULL, revoked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_local_sessions_user ON local_sessions(user_id);
        CREATE TABLE IF NOT EXISTS local_login_failures (
          fingerprint TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_login_failures ON local_login_failures(fingerprint,created_at);
        """)

        # v0.3.4.2: optional per-user permission restrictions; existing users
        # keep their full role-based permissions (NULL override).
        if 'capabilities_json' not in {r['name'] for r in db.execute('PRAGMA table_info(local_users)')}:
            db.execute('ALTER TABLE local_users ADD COLUMN capabilities_json TEXT DEFAULT NULL')

        # v0.3.2.2: governance is separate from provider-reported approval metadata.
        db.executescript("""
        CREATE TABLE IF NOT EXISTS agent_governance (
          tenant_id TEXT NOT NULL REFERENCES tenants(id),
          agent_id TEXT NOT NULL,
          business_owner_user_id TEXT REFERENCES local_users(id) ON DELETE RESTRICT,
          approval_status TEXT NOT NULL DEFAULT 'not_reviewed'
            CHECK(approval_status IN ('not_reviewed','pending','approved','rejected')),
          justification TEXT NOT NULL DEFAULT '',
          requested_budget_usd REAL NOT NULL DEFAULT 0 CHECK(requested_budget_usd >= 0),
          requested_cost_center TEXT NOT NULL DEFAULT '',
          submitted_by TEXT, submitted_at TEXT,
          decided_by TEXT, decided_at TEXT, decision_reason TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL,
          PRIMARY KEY (tenant_id, agent_id)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_governance_owner
          ON agent_governance(tenant_id,business_owner_user_id);
        """)
        governance_cols = {row['name'] for row in db.execute('PRAGMA table_info(agent_governance)')}
        if 'requested_cost_center' not in governance_cols:
            db.execute("ALTER TABLE agent_governance ADD COLUMN requested_cost_center TEXT NOT NULL DEFAULT ''")
        audit_cols = {row['name'] for row in db.execute('PRAGMA table_info(audit_events)')}
        if 'details_json' not in audit_cols:
            db.execute("ALTER TABLE audit_events ADD COLUMN details_json TEXT NOT NULL DEFAULT '{}'")
        # Expand role CHECK on existing databases without altering user IDs or sessions.
        # Rebuild in one explicit transaction with FK checks temporarily disabled;
        # keep the original database untouched if migration fails.
        user_schema = db.execute("SELECT sql FROM sqlite_master WHERE name='local_users' AND type='table'").fetchone()
        if user_schema and "'business_owner'" not in user_schema['sql']:
            db.commit()
            db.execute('PRAGMA foreign_keys=OFF')
            try:
                db.execute('BEGIN IMMEDIATE')
                db.execute("""CREATE TABLE local_users_role_new (
                  id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                  display_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
                  password_hash TEXT NOT NULL,
                  role TEXT NOT NULL CHECK(role IN ('admin','provider_admin','agent_owner','business_owner','auditor','viewer')),
                  scope_json TEXT NOT NULL DEFAULT '{"kind":"all"}',
                  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                  must_change_password INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL, password_changed_at TEXT, last_login_at TEXT
                )""")
                db.execute("""INSERT INTO local_users_role_new
                  (id,username,display_name,email,password_hash,role,scope_json,active,
                   must_change_password,created_at,password_changed_at,last_login_at)
                  SELECT id,username,display_name,email,password_hash,role,scope_json,active,
                   must_change_password,created_at,password_changed_at,last_login_at FROM local_users""")
                db.execute('DROP TABLE local_users')
                db.execute('ALTER TABLE local_users_role_new RENAME TO local_users')
                violations = db.execute('PRAGMA foreign_key_check').fetchall()
                if violations:
                    raise RuntimeError('Local user role migration failed foreign-key verification')
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.execute('PRAGMA foreign_keys=ON')
        # Versioned, company-scoped advisory policy catalog. Definitions are rules, not sample data.
        # Initialize idempotently and preserve any customer policy configuration on restart.
        db.executescript("""
        CREATE TABLE IF NOT EXISTS policy_rules (
          tenant_id TEXT NOT NULL REFERENCES tenants(id),
          code TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
          severity TEXT NOT NULL CHECK(severity IN ('high','medium','low')),
          stale_after_days INTEGER NOT NULL DEFAULT 30 CHECK(stale_after_days BETWEEN 1 AND 365),
          version INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL,
          updated_by TEXT NOT NULL DEFAULT 'system',
          PRIMARY KEY(tenant_id,code)
        );
        CREATE TABLE IF NOT EXISTS policy_evaluation_runs (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id),
          actor TEXT NOT NULL,
          evaluated_at TEXT NOT NULL,
          agents_evaluated INTEGER NOT NULL,
          open_findings INTEGER NOT NULL,
          resolved_findings INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_policy_runs_tenant_date ON policy_evaluation_runs(tenant_id,evaluated_at);
        CREATE TABLE IF NOT EXISTS policy_findings (
          tenant_id TEXT NOT NULL REFERENCES tenants(id),
          agent_id TEXT NOT NULL,
          policy_code TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('open','resolved')),
          severity TEXT NOT NULL CHECK(severity IN ('high','medium','low')),
          message TEXT NOT NULL,
          evidence_json TEXT NOT NULL DEFAULT '{}',
          first_seen_at TEXT NOT NULL,
          last_evaluated_at TEXT NOT NULL,
          resolved_at TEXT,
          PRIMARY KEY(tenant_id,agent_id,policy_code)
        );
        CREATE INDEX IF NOT EXISTS idx_policy_findings_tenant_status ON policy_findings(tenant_id,status);
        """)
        # Optional CVE references: a link is not evidence of affected status by itself.
        # Never fabricate CVSS scores or infer affected components from agent names.
        db.executescript("""
        CREATE TABLE IF NOT EXISTS agent_vulnerability_links (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          cve_id TEXT NOT NULL,
          component_name TEXT NOT NULL,
          component_version TEXT NOT NULL DEFAULT '',
          assessment TEXT NOT NULL CHECK(assessment IN ('under_review','affected','not_affected')),
          evidence_source TEXT NOT NULL DEFAULT '',
          assessed_by TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(tenant_id,agent_id,cve_id,component_name,component_version)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_vulnerability_lookup
          ON agent_vulnerability_links(tenant_id,agent_id,assessment);
        """)
        remediation_cols = {row['name'] for row in db.execute('PRAGMA table_info(policy_findings)')}
        for col, definition in (
            ('remediation_note', "TEXT NOT NULL DEFAULT ''"),
            ('remediation_due_date', 'TEXT'),
            ('remediation_updated_by', 'TEXT'),
            ('remediation_updated_at', 'TEXT'),
        ):
            if col not in remediation_cols:
                db.execute(f'ALTER TABLE policy_findings ADD COLUMN {col} {definition}')
        # v0.3.3: additive, tenant-scoped runtime evidence. No seed data and no
        # legacy record rewrite. Spans are metadata only, not prompts or payloads.
        db.executescript("""
        CREATE TABLE IF NOT EXISTS runtime_runs (
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
          source TEXT NOT NULL, external_run_id TEXT NOT NULL,
          trace_id TEXT, status TEXT NOT NULL CHECK(status IN ('success','failure','unknown')),
          started_at TEXT NOT NULL, ended_at TEXT, duration_ms REAL,
          first_ingested_at TEXT NOT NULL, last_ingested_at TEXT NOT NULL,
          UNIQUE(tenant_id,source,agent_id,external_run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_runtime_runs_tenant_time
          ON runtime_runs(tenant_id,started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_runtime_runs_agent_time
          ON runtime_runs(tenant_id,agent_id,started_at DESC);
        CREATE TABLE IF NOT EXISTS runtime_spans (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runtime_runs(id) ON DELETE CASCADE,
          tenant_id TEXT NOT NULL, span_id TEXT NOT NULL, parent_span_id TEXT,
          trace_id TEXT NOT NULL, kind TEXT NOT NULL
          CHECK(kind IN ('agent','model','tool','mcp','other')),
          name TEXT NOT NULL, status TEXT NOT NULL
          CHECK(status IN ('success','failure','unknown')),
          started_at TEXT NOT NULL, ended_at TEXT, duration_ms REAL,
          UNIQUE(run_id,span_id)
        );
        CREATE INDEX IF NOT EXISTS idx_runtime_spans_run ON runtime_spans(run_id);
        CREATE TABLE IF NOT EXISTS runtime_collection_status (
          tenant_id TEXT NOT NULL, source TEXT NOT NULL,
          last_success_at TEXT NOT NULL, window_start TEXT NOT NULL,
          window_end TEXT NOT NULL, metadata_rows INTEGER NOT NULL,
          trace_groups INTEGER NOT NULL, eligible INTEGER NOT NULL,
          imported INTEGER NOT NULL, replayed INTEGER NOT NULL, failed INTEGER NOT NULL,
          PRIMARY KEY (tenant_id, source)
        );
        """)
        # v0.3.4: separate observed model usage from legacy manually recorded cost.
        # Null token counts mean unknown, never zero. Idempotent schema upgrades.
        db.executescript("""
        CREATE TABLE IF NOT EXISTS finops_usage (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          run_id TEXT NOT NULL REFERENCES runtime_runs(id) ON DELETE RESTRICT,
          source TEXT NOT NULL,
          external_run_id TEXT NOT NULL,
          operation_id TEXT NOT NULL,
          occurred_at TEXT NOT NULL,
          model_id TEXT,
          input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens>=0),
          output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens>=0),
          evidence TEXT NOT NULL,
          first_ingested_at TEXT NOT NULL,
          UNIQUE(tenant_id,source,agent_id,external_run_id,operation_id)
        );
        CREATE INDEX IF NOT EXISTS idx_finops_usage_tenant_time ON finops_usage(tenant_id,occurred_at DESC);
        CREATE INDEX IF NOT EXISTS idx_finops_usage_agent_time ON finops_usage(tenant_id,agent_id,occurred_at DESC);
        CREATE TABLE IF NOT EXISTS finops_rate_cards (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          provider TEXT NOT NULL,
          model_id TEXT NOT NULL,
          currency TEXT NOT NULL DEFAULT 'USD' CHECK(currency='USD'),
          input_usd_per_million TEXT NOT NULL,
          output_usd_per_million TEXT NOT NULL,
          valid_from TEXT NOT NULL,
          valid_until TEXT,
          source_url TEXT NOT NULL,
          configured_by TEXT NOT NULL,
          configured_at TEXT NOT NULL,
          UNIQUE(tenant_id,provider,model_id,valid_from)
        );
        """)
        # v0.3.4.1: read-only Azure Cost Management ActualCost scope evidence.
        # Provider charges are NEVER automatically allocated to individual agents.
        db.executescript("""
        CREATE TABLE IF NOT EXISTS finops_azure_scope_costs (
          tenant_id TEXT NOT NULL,
          scope TEXT NOT NULL,
          resource_id TEXT NOT NULL,
          usage_day TEXT NOT NULL,
          currency TEXT NOT NULL,
          amount TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'azure_cost_management_actual_cost',
          collected_at TEXT NOT NULL,
          PRIMARY KEY(tenant_id,scope,resource_id,usage_day,currency)
        );
        CREATE INDEX IF NOT EXISTS idx_finops_azure_scope_day
          ON finops_azure_scope_costs(tenant_id,usage_day,scope);
        """)
        for tenant in db.execute('SELECT id FROM tenants').fetchall():
            for rule in DEFAULT_RULES:
                db.execute("""INSERT OR IGNORE INTO policy_rules
                    (tenant_id,code,enabled,severity,stale_after_days,updated_at,updated_by)
                    VALUES (?,?,?,?,?,?,?)""",
                    (tenant['id'],rule['code'],1,rule['severity'],30,iso(utc_now()),'system'))
