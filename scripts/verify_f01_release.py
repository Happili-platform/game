# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only F01 deployment and regression verification."""

import os
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
results = []


def check(name, fn):
    try:
        message = fn()
        results.append(("PASS", name, str(message or "")))
    except Exception as exc:
        results.append(("FAIL", name, str(exc)))


def run(*args, env=None):
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise RuntimeError(detail[-1200:])
    return result.stdout.strip()


def branch():
    actual = run("git", "branch", "--show-current")
    expected = "feature/32-canonical-agent-identity"
    assert actual == expected, f"Expected {expected}, got {actual}"
    return actual


def docker_config():
    run("docker", "compose", "config", "--quiet")
    config = run("docker", "compose", "config")
    assert "GAME_LOCAL_DOCKER_GATEWAY" in config
    assert "/.local/share/game" in config
    assert "/app/data" in config
    assert "/app/vault" in config
    return "Valid; local database and vault configured"


def docker_runtime():
    container = run("docker", "compose", "ps", "-q", "game")
    assert container, "GAMe container is not running"
    status = run(
        "docker", "inspect", "-f",
        "{{.State.Running}}", container,
    )
    assert status == "true", f"Container running: {status}"
    port = run("docker", "compose", "port", "game", "8000")
    assert port in ("127.0.0.1:8000", "[::1]:8000"), (
        f"Unexpected port exposure: {port}"
    )
    return port


def health():
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )
    with opener.open(
        "http://127.0.0.1:8000/api/health",
        timeout=10,
    ) as response:
        import json
        payload = json.load(response)
        assert response.status == 200
        assert payload["status"] == "ok"
        return f"HTTP 200; version {payload.get('version')}"


def database():
    path = Path.home() / ".local/share/game/game.db"
    assert path.is_file(), f"Missing database: {path}"

    with sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro",
        uri=True,
    ) as db:
        db.row_factory = sqlite3.Row

        assert db.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok", "SQLite integrity failed"

        assert not db.execute(
            "PRAGMA foreign_key_check"
        ).fetchall(), "Foreign-key violations found"

        def count(query):
            return db.execute(query).fetchone()[0]

        inventory = count("""
            SELECT
                (SELECT COUNT(*) FROM agents) +
                (SELECT COUNT(*) FROM discovered_agents)
        """)

        references = count(
            "SELECT COUNT(*) FROM agent_legacy_references"
        )

        missing_manual = count("""
            SELECT COUNT(*) FROM agents a
            WHERE NOT EXISTS (
                SELECT 1 FROM agent_legacy_references r
                WHERE r.tenant_id=a.tenant_id
                  AND r.source_table='agents'
                  AND r.legacy_agent_id=a.id
            )
        """)

        missing_discovered = count("""
            SELECT COUNT(*) FROM discovered_agents a
            WHERE NOT EXISTS (
                SELECT 1 FROM agent_legacy_references r
                WHERE r.tenant_id=a.tenant_id
                  AND r.source_table='discovered_agents'
                  AND r.legacy_agent_id=a.id
            )
        """)

        broken_mappings = count("""
            SELECT COUNT(*)
            FROM agent_identity_mappings m
            LEFT JOIN discovered_agents a
              ON a.tenant_id=m.tenant_id
             AND a.connection_id=m.connection_id
             AND a.external_id=m.external_id
            LEFT JOIN agent_legacy_references r
              ON r.tenant_id=a.tenant_id
             AND r.source_table='discovered_agents'
             AND r.legacy_agent_id=a.id
            WHERE m.provider='google_agent_engine'
              AND (
                  m.verification_status!='verified'
                  OR a.id IS NULL
                  OR r.canonical_agent_id IS NULL
                  OR r.canonical_agent_id!=m.canonical_agent_id
              )
        """)

        open_conflicts = count("""
            SELECT COUNT(*) FROM agent_identity_conflicts
            WHERE status='open'
        """)

        assert missing_manual == 0, (
            f"{missing_manual} manual agents lack canonical references"
        )
        assert missing_discovered == 0, (
            f"{missing_discovered} discovered agents lack references"
        )
        assert broken_mappings == 0, (
            f"{broken_mappings} Google mappings are inconsistent"
        )
        assert open_conflicts == 0, (
            f"{open_conflicts} unresolved identity conflicts"
        )

        canonical = count(
            "SELECT COUNT(*) FROM canonical_agents"
        )
        mappings = count(
            "SELECT COUNT(*) FROM agent_identity_mappings"
        )

        return (
            f"Inventory {inventory}; references {references}; "
            f"canonical identities {canonical}; "
            f"verified mappings {mappings}; "
            "integrity OK"
        )


def backups():
    directory = Path.home() / ".local/share/game"
    for filename in (
        "game-pre-f01-backup.db",
        "game-f01-ready.db",
    ):
        path = directory / filename
        assert path.is_file(), f"Missing: {path}"
    return "Recovery backup and staged candidate available"


def regression():
    import re

    env = os.environ.copy()
    env.pop("GAME_DB_PATH", None)
    env["PYTHONPATH"] = "src:."

    output = run(
        sys.executable, "-m", "pytest", "-q",
        env=env,
    )

    match = re.search(r"(\d+) passed\b", output)
    if not match:
        raise RuntimeError(
            "No successful pytest summary: " + output[-500:]
        )

    passed = int(match.group(1))
    assert passed >= 251, (
        f"Regression suite unexpectedly reduced to {passed} tests"
    )

    return f"{passed} tests passed"


def source_checks():
    run("git", "diff", "--check")
    run(
        sys.executable, "-m", "compileall", "-q",
        "src/game",
    )
    return "Syntax and whitespace checks passed"


def git_changes():
    output = run("git", "status", "--short")
    return (
        "Uncommitted changes present (expected before commit)"
        if output else
        "Working tree clean"
    )


checks = [
    ("Feature branch", branch),
    ("Docker configuration", docker_config),
    ("Docker runtime and port", docker_runtime),
    ("Application health", health),
    ("Active F01 database", database),
    ("Recovery files", backups),
    ("Regression suite", regression),
    ("Source checks", source_checks),
    ("Git working tree", git_changes),
]

for name, function in checks:
    check(name, function)

print("\n" + "=" * 65)
print("GAMe F01 RELEASE VERIFICATION")
print("=" * 65)

for status, name, detail in results:
    print(f"[{status}] {name}")
    if detail:
        print(f"       {detail[:300]}")

failures = sum(status == "FAIL" for status, _, _ in results)

print("-" * 65)
print(
    f"RESULT: {len(results) - failures}/{len(results)} checks passed"
)
print("STATUS:", "PASS" if not failures else "FAIL")
print("=" * 65)

sys.exit(1 if failures else 0)
