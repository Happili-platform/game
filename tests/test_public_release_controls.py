# SPDX-License-Identifier: AGPL-3.0-only
"""Static safeguards for Community Edition attribution and deployment defaults."""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/Happili-platform/game"


def test_copyright_and_license_notice():
    copyright_text = (ROOT / "COPYRIGHT").read_text()
    assert "Copyright (C) 2026 Siddhartha Pillutla" in copyright_text
    assert "Published and maintained by Happili Platform" in copyright_text
    assert "No assignment of copyright to a legal entity" in copyright_text
    assert "AGPL-3.0-only" in copyright_text
    assert REPO in copyright_text
    assert (ROOT / "LICENSE").read_text().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")


def test_ui_source_links_reference_community_repo():
    for file in ("static/login.html", "static/password.html"):
        value = (ROOT / file).read_text()
        assert REPO in value
    assert REPO in (ROOT / "docs/SOURCE_CODE_LINK.md").read_text()


def test_compose_and_docker_default_to_password_auth():
    docker = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "compose.yaml").read_text()
    assert "GAME_AUTH_MODE=password" in docker
    assert 'GAME_AUTH_MODE: "password"' in compose
    assert "GAME_AUTH_MODE=local" not in docker
    assert 'GAME_AUTH_MODE: "local"' not in compose
    assert "127.0.0.1:8000:8000" in compose
    assert "COPY scripts ./scripts" in docker


def test_dco_trailers():
    path = ROOT / "scripts/check_dco.py"
    spec = importlib.util.spec_from_file_location("check_dco", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.valid_signoff("Change\n\nSigned-off-by: Jane Doe <jane@example.com>", "jane@example.com")
    assert not module.valid_signoff("Change with no trailer", "jane@example.com")
    assert not module.valid_signoff("Signed-off-by: Jane Doe <other@example.com>", "jane@example.com")
