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

    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        assert db.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"

        assert not db.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        expected = {
            "discovered_agents": 6,
            "canonical_agents": 6,
            "agent_legacy_references": 6,
            "agent_identity_mappings": 0,
            "agent_identity_conflicts": 0,
        }

        actual = {
            table: db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in expected
        }

        assert actual == expected, (
            f"Expected {expected}; actual {actual}"
        )

    return "Integrity OK; identities 6; legacy refs 6"


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
    env = os.environ.copy()
    env.pop("GAME_DB_PATH", None)
    env["PYTHONPATH"] = "src:."

    output = run(
        sys.executable, "-m", "pytest", "-q",
        env=env,
    )
    assert "247 passed" in output, (
        f"Unexpected test result: {output[-500:]}"
    )
    return "247 tests passed"


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
    ("247-test regression suite", regression),
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
