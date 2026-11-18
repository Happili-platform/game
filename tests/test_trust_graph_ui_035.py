# SPDX-License-Identifier: AGPL-3.0-only
"""Static UI integration contract for Trust Graph; no browser automation required."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT/'static'/'index.html').read_text()
JS = (ROOT/'static'/'app.js').read_text()
CSS = (ROOT/'static'/'style.css').read_text()


def test_trust_graph_page_and_three_tabs_exist():
    assert 'data-view="trustGraph"' in HTML
    assert 'id="trustGraphView"' in HTML
    for tab in ('graph', 'inventory', 'evidence'):
        assert f'data-trust-tab="{tab}"' in HTML
        assert f'id="trust{tab.title()}Tab"' in HTML
    assert 'id="trustGraphCanvas"' in HTML
    assert 'id="trustEvidenceRows"' in HTML


def test_ui_is_read_only_and_capability_gated():
    assert "caps.has('agents.view')" in JS
    assert "view==='trustGraph'" in JS
    assert "api('/api/trust-graph')" in JS
    ui = JS.split('// v0.3.5 Trust Graph UI: read-only')[1]
    assert "method:'POST'" not in ui
    assert "method:'PATCH'" not in ui
    assert "method:'DELETE'" not in ui
    assert 'No Trust Graph relationships yet' in ui
    assert 'source verification' in ui


def test_trust_graph_style_and_cache_version():
    assert '.trust-graph-canvas' in CSS
    assert 'style.css?v=0.3.5-provider-filter-zoom1' in HTML
    assert 'app.js?v=0.3.5-provider-filter-zoom1' in HTML
