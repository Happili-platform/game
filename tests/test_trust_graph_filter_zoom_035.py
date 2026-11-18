# SPDX-License-Identifier: AGPL-3.0-only
"""Static UI contract for provider filters and graph zoom controls."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'static/index.html').read_text()
JS = (ROOT / 'static/app.js').read_text()
CSS = (ROOT / 'static/style.css').read_text()


def test_provider_filter_and_search_controls():
    for element in ('providerInventoryFilter', 'providerInventorySearch', 'providerInventoryCount'):
        assert f'id="{element}"' in HTML
    assert 'function renderProviderInventory()' in JS
    assert "conn?.provider||'unknown'" in JS
    assert "api('/api/provider-inventory')" in JS
    assert "$('#providerInventoryFilter').addEventListener('change',renderProviderInventory)" in JS
    assert "$('#providerInventorySearch').addEventListener('input',renderProviderInventory)" in JS


def test_graph_zoom_controls_and_bounded_scale():
    for element in ('trustZoomIn', 'trustZoomOut', 'trustZoomFit', 'trustZoomLevel'):
        assert f'id="{element}"' in HTML
    assert 'function trustFitScale()' in JS
    assert 'function trustApplyZoom(scale)' in JS
    assert 'function trustFitView()' in JS
    assert 'trustViewport.scale*1.25' in JS
    assert 'trustViewport.scale/1.25' in JS
    assert 'trustViewport.width=w;trustViewport.height=h;trustFitView()' in JS
    assert '.trust-zoom-toolbar' in CSS


def test_ui_readonly_and_asset_cache_busting():
    assert 'method:\'POST\'' not in JS.split('// v0.3.5 Trust Graph UI: read-only')[1]
    assert 'app.js?v=0.3.5-provider-filter-zoom1' in HTML
    assert 'style.css?v=0.3.5-provider-filter-zoom1' in HTML
