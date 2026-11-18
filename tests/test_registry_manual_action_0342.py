# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_manual_registration_action_is_only_in_registry():
    html=(ROOT/'static/index.html').read_text()
    header=html.split('<header class="topbar">',1)[1].split('</header>',1)[0]
    registry=html.split('<section id="agentsView"',1)[1].split('</section>',2)[0]
    assert 'newAgentBtn' not in header
    assert 'id="newAgentBtn"' in registry
    assert 'id="registryMoreActions"' in registry
    assert 'Register unmanaged agent' in registry
    assert 'id="agentDialog"' in html

def test_ui_permission_gates_manual_action():
    js=(ROOT/'static/app.js').read_text()
    assert "$('#registryMoreActions').hidden=!caps.has('agents.register')" in js
    assert "$('#newAgentBtn').hidden=!caps.has('agents.register')" in js
    assert "$('#agentDialog').showModal()" in js

def test_css_variables_remain_in_stylesheet():
    css=(ROOT/'static/style.css').read_text()
    assert '.registry-actions-menu' in css
    assert '--brand-blue' in css
