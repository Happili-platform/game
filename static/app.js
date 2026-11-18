// SPDX-License-Identifier: AGPL-3.0-only
const $ = (selector) => document.querySelector(selector);
let agents = [];
let overview = null;
let selectedAgent = null;
const agentSpend = a => a.spend_observed===false ? '<span class="muted">Not tracked</span>' : money(a.monthly_spend_usd);
const money = (n) => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(n ?? 0);
const safe = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const riskPill = (risk) => `<span class="risk-pill risk-${safe(risk)}">${safe(risk === 'clear' ? 'Clear' : risk + ' risk')}</span>`;
const shortDate = (date) => date ? new Date(date).toLocaleDateString('en-US',{year:'numeric',month:'short',day:'numeric'}) : 'Not recorded';
const agentCell = a => `<strong>${safe(a.name)}</strong><small>${safe(a.environment)} · ${safe(a.lifecycle_status)}</small>`;

let sessionCsrf = null;
let passwordMode = false;
const sessionReady = fetch('/api/auth/session',{credentials:'same-origin'}).then(async response => {
  if(response.ok){const data=await response.json();passwordMode=true;sessionCsrf=data.csrf_token;return data;}
  if(response.status===401){passwordMode=true;location.replace('/login');}
  return null; // Explicit OIDC or legacy local mode, when password login is disabled.
}).catch(()=>null);
async function api(path, options = {}) {
  await sessionReady;
  const method=(options.method||'GET').toUpperCase();
  const headers={ 'Content-Type':'application/json', ...(options.headers||{}) };
  if(passwordMode && !['GET','HEAD','OPTIONS'].includes(method)) headers['X-CSRF-Token']=sessionCsrf;
  const response=await fetch(path,{...options,credentials:'same-origin',headers});
  const data=await response.json();
  if(response.status===401 && passwordMode){location.replace('/login');throw new Error('Session expired');}
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
  return data;
}

async function refresh() {
  try {
    [agents, overview] = await Promise.all([api('/api/agents'), api('/api/overview')]);
    $('#monthLabel').textContent = new Date(`${overview.month}-01T12:00:00`).toLocaleDateString('en-US',{month:'long',year:'numeric'}).toUpperCase();
    $('#metrics').innerHTML = [
      {label:'REGISTERED AGENTS',value:overview.totals.agents,foot:`${overview.totals.active} marked active`,symbol:'⬡'},
      {label:'MISSING OWNERS',value:overview.totals.missing_owners,foot:'Ownership needs review',symbol:'♙',tone:'warn'},
      {label:'FLAGGED AGENTS',value:overview.totals.flagged_agents,foot:`${overview.totals.high_risk_agents} high-risk`,symbol:'⚑',tone:'danger'},
      {label:'RECORDED MONTHLY SPEND',value:overview.totals.monthly_spend_usd===null?'Restricted':money(overview.totals.monthly_spend_usd),foot:'Not invoice-reconciled',symbol:'＄'}
    ].map(m=>`<article class="metric"><div class="metric-top">${safe(m.label)}<span class="metric-icon">${m.symbol}</span></div><div class="metric-value ${m.tone || ''}">${safe(m.value)}</div><div class="metric-foot">${safe(m.foot)}</div></article>`).join('');
    renderSpend(); renderAttention(); renderOverviewTable(); renderAgentTable();
  } catch(error) {
    $('#metrics').innerHTML = `<div class="state-error">Unable to load API data: ${safe(error.message)}</div>`;
  }
}
function renderSpend() {
  const rows = overview.by_provider.filter(p=>p.spend_usd!=null&&p.spend_usd>0).slice(0,6);
  const max = Math.max(1,...rows.map(p=>p.spend_usd));
  $('#spendBars').innerHTML = rows.length ? rows.map(p=>`<div><div class="bar-top"><strong>${safe(p.provider)}</strong><span>${money(p.spend_usd)}</span></div><div class="track"><div class="fill" style="width:${Math.max(2,Math.round(p.spend_usd/max*100))}%"></div></div></div>`).join('') : '<div class="empty">No usage events recorded this month.</div>';
}
function renderAttention() {
  $('#attentionList').innerHTML = overview.attention.length ? overview.attention.slice(0,5).map(a=>`<div class="attention-row" role="button" tabindex="0" data-agent="${safe(a.id)}"><div><div class="attention-name">${safe(a.name)}</div><div class="attention-text">${safe(a.findings[0]?.message || '')}</div></div>${riskPill(a.risk_level)}<span class="attention-chevron">›</span></div>`).join('') : '<div class="empty">No advisory findings from the current rules.</div>';
}
function row(a, registry=false) {
  return `<tr class="agent-row" data-agent="${safe(a.id)}"><td>${agentCell(a)}</td><td>${safe(a.provider)}</td><td>${safe(a.business_owner_name || a.owner_email || 'Not assigned')}</td>${registry ? `<td>${safe(a.approval_status)}</td>` : ''}<td>${riskPill(a.risk_level)}</td><td><strong>${agentSpend(a)}</strong></td><td class="row-arrow">›</td></tr>`;
}
function renderOverviewTable() { $('#overviewTable').innerHTML = agents.slice(0,6).map(a=>row(a)).join('') || '<tr><td colspan="6">No registered agents yet.</td></tr>'; }
function renderAgentTable() {
  const query=$('#searchAgents').value.trim().toLowerCase(), risk=$('#riskFilter').value;
  const filtered=agents.filter(a=>(!risk || a.risk_level===risk) && (!query || [a.name,a.provider,a.owner_email,a.business_owner_name,a.cost_center].some(v=>String(v||'').toLowerCase().includes(query))));
  $('#agentTable').innerHTML=filtered.map(a=>row(a,true)).join('') || '<tr><td colspan="7">No matching agents.</td></tr>';
}
async function refreshPolicies() {
  const output=$('#policyList');
  const snapshot=$('#policySnapshot');
  try {
    const [catalog, history] = await Promise.all([api('/api/policies'),api('/api/policies/findings?limit=200')]);
    $('#policyRuleCount').textContent = `${catalog.rules.filter(p=>p.enabled).length} OF ${catalog.rules.length} ACTIVE`;
    $('#policySummary').textContent = `${catalog.agents_visible} visible agents · Live advisory preview only. ${catalog.notice}`;
    $('#runPolicyEvaluationBtn').hidden = !catalog.can_evaluate;
    output.innerHTML = catalog.rules.map((r,i)=>`<article class="policy-row" data-policy-code="${safe(r.code)}">
      <div class="policy-number">${String(i+1).padStart(2,'0')}</div>
      <div class="policy-body">
        <div class="policy-title-line"><strong>${safe(r.title)}</strong><span class="policy-code">${safe(r.code)}</span></div>
        <p>${safe(r.description)}</p><div class="policy-remediation">Recommended: ${safe(r.remediation)}</div>
        <div class="policy-controls">${catalog.can_manage ? `
          <label><input class="policy-enabled" type="checkbox" ${r.enabled?'checked':''}/> Enabled</label>
          <label>Severity <select class="policy-severity">${['high','medium','low'].map(s=>`<option value="${s}" ${r.severity===s?'selected':''}>${s}</option>`).join('')}</select></label>
          ${r.code==='STALE_AGENT'?`<label>Inactivity days <input class="policy-stale-days" type="number" min="1" max="365" value="${Number(r.stale_after_days)}"/></label>`:''}
          <button type="button" class="secondary-btn policy-save" data-policy-save="${safe(r.code)}">Save</button>`:
          `<span class="policy-code">${r.enabled?'Enabled':'Disabled'} · ${safe(r.severity)}</span>`}
          <span class="policy-affected">${r.enabled?safe(r.affected_agents):'—'} live findings</span>
        </div>
        <span class="policy-inline-error error" role="alert"></span>
      </div><div>${r.enabled?riskPill(r.severity):'<span class="tag">Disabled</span>'}</div>
    </article>`).join('');
    const last=catalog.last_recorded_evaluation;
    const open=history.filter(r=>r.status==='open');
    const resolved=history.filter(r=>r.status==='resolved');
    $('#policySnapshotHeading').textContent = last ? `Recorded evaluation · ${shortDate(last.evaluated_at)}` : 'No evaluation snapshot recorded';
    snapshot.innerHTML = last ? `<p class="provider-helper">Last run: ${last.agents_evaluated} agents · ${last.open_findings} open findings · ${last.resolved_findings} resolved during the run. Current snapshot view: ${open.length} open and ${resolved.length} resolved records returned.</p>`+
      (history.length?`<div class="policy-snapshot-list">${history.slice(0,30).map(f=>`<div class="policy-snapshot-item" data-remediation-agent="${safe(f.agent_id)}" data-remediation-code="${safe(f.policy_code)}"><strong>${safe(f.policy_code)}</strong> <span class="policy-code">${safe(f.agent_id)}</span> ${f.status==='open'?riskPill(f.severity):'<span class="tag">Resolved</span>'}<p>${safe(f.message)}</p>
      ${f.remediation_note?`<p><strong>Remediation:</strong> ${safe(f.remediation_note)} ${f.remediation_due_date?'· Due '+safe(f.remediation_due_date):''}</p>`:''}
      ${catalog.can_remediate && f.status==='open'?`<details class="policy-remediation-form"><summary>Document remediation</summary><label>Action taken or planned<textarea class="policy-note" rows="2" maxlength="1500" minlength="10" placeholder="Document the owner, activity and next step" required>${safe(f.remediation_note||'')}</textarea></label><label>Target date (optional)<input class="policy-due-date" type="date" value="${safe(f.remediation_due_date||'')}"/></label><button type="button" class="secondary-btn" data-save-remediation>Save remediation note</button><span class="policy-remediation-error error" role="alert"></span></details>`:''}</div>`).join('')}</div>`:'<div class="empty">No historical findings recorded.</div>')
      :'<p class="provider-helper">Select Run evaluation (Admin only) to save an evidence-backed snapshot and resolution history. Live risk checks are already calculated in the Agent Registry.</p>';
  } catch(error) {
    output.innerHTML=`<div class="state-error">Unable to load policies: ${safe(error.message)}</div>`;
    snapshot.innerHTML='';
  }
}
$('#policyList').addEventListener('click',async e=>{
  const btn=e.target.closest('[data-policy-save]'); if(!btn) return;
  const block=btn.closest('[data-policy-code]');
  const code=btn.dataset.policySave;
  const payload={enabled:block.querySelector('.policy-enabled').checked,
    severity:block.querySelector('.policy-severity').value};
  const stale=block.querySelector('.policy-stale-days');
  if(stale) payload.stale_after_days=Number(stale.value);
  const error=block.querySelector('.policy-inline-error'); error.textContent='';
  btn.disabled=true;
  try {
    await api(`/api/policies/${encodeURIComponent(code)}`,{method:'PATCH',body:JSON.stringify(payload)});
    await Promise.all([refreshPolicies(),refresh()]);
  } catch(ex){error.textContent=ex.message;btn.disabled=false;}
});
$('#policySnapshot').addEventListener('click',async e=>{
  const btn=e.target.closest('[data-save-remediation]');if(!btn)return;
  const row=btn.closest('[data-remediation-agent]');
  const agent=row.dataset.remediationAgent, code=row.dataset.remediationCode;
  const note=row.querySelector('.policy-note').value.trim();
  const due_date=row.querySelector('.policy-due-date').value||null;
  const error=row.querySelector('.policy-remediation-error');error.textContent='';
  btn.disabled=true;
  try {
    await api(`/api/policies/findings/${encodeURIComponent(agent)}/${encodeURIComponent(code)}/remediation`,{
      method:'PATCH',body:JSON.stringify({note,due_date})});
    $('#policyActionStatus').textContent='Remediation recorded. The finding remains open until evidence shows the underlying issue is resolved.';
    await refreshPolicies();
  } catch(ex){error.textContent=ex.message;btn.disabled=false;}
});
$('#runPolicyEvaluationBtn').addEventListener('click', async e=>{
  e.currentTarget.disabled=true;const note=$('#policyActionStatus');note.textContent='Running advisory evaluation…';
  try {const result=await api('/api/policies/evaluate',{method:'POST'});
    note.textContent=`Recorded ${result.open_findings} open findings across ${result.agents_evaluated} agents; ${result.resolved_in_run} resolved. No cloud actions taken.`;
    await refreshPolicies();
  } catch(error){note.textContent=error.message;}
  finally{e.currentTarget.disabled=false;}
});

const pageDetails={trustGraph:['Trust Graph','Agent-to-Tool Trust Graph','Evidence-backed visibility into declared tools and reported relationships; no live provider execution.'],finops:['Agentic FinOps','Agentic FinOps','Actual token consumption and separately classified cost estimates.'],runtime:['Runtime observability','Agent runtime observability','Recorded executions, statuses, latency and trace/span evidence.'],audit:['Audit log','Administration · Audit Log','Review GAME administration, access, and business approval events.'],users:['Admin · Users & roles','Company access administration','Manage assigned roles, inherited capabilities and provider or agent scopes.'],overview:['Overview','Enterprise agent overview','A unified view of registered and discovered agents, ownership, risk and recorded usage.'],agents:['Agent registry','Your enterprise agent registry','Manual and discovered agent records, with explicit provenance.'],policies:['Policy checks','Advisory policy framework','Simple, explainable checks evaluated against locally recorded metadata.'],connections:['Provider connections','Connect AI platforms','Onboard Microsoft, Google or AWS projects using read-only agent discovery.']};
function showView(view) {
  if (!pageDetails[view]) return;
  if(view==='users' && (!currentIdentity || !(currentIdentity.capabilities||[]).includes('members.manage'))) return;
  if(view==='audit' && (!currentIdentity || !(currentIdentity.capabilities||[]).includes('audit.view'))) return;
  if(view==='trustGraph' && !(currentIdentity?.capabilities||[]).includes('agents.view')) return;
  if(view==='runtime' && !(currentIdentity?.capabilities||[]).includes('runtime.view')) return;
  if(view==='finops' && !(currentIdentity?.capabilities||[]).includes('finops.usage.view')) return;
  Object.keys(pageDetails).forEach(v => { $(`#${v}View`).hidden = v !== view; });
  document.querySelectorAll('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
  const [crumb,title,subtitle]=pageDetails[view]; $('#crumb').textContent=crumb;$('#pageTitle').textContent=title;$('#pageSubtitle').textContent=subtitle;
  if(view==='trustGraph') refreshTrustGraph();
  if(view==='connections') refreshConnections();
  if(view==='users'){ refreshMembers(); loadCompanySettings(); }
  if(view==='audit')refreshAuditLog();
  if(view==='policies')refreshPolicies();
  if(view==='runtime')refreshRuntime();
  if(view==='finops')refreshFinops();
  // Persist the selected view so refreshes and direct links open the intended tab.
  if(window.location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
}
document.addEventListener('click',event=>{
  const viewButton=event.target.closest('[data-view]'); if(viewButton){showView(viewButton.dataset.view);return;}
  const closer=event.target.closest('[data-close]');if(closer){$(`#${closer.dataset.close}`).close();return;}
  const item=event.target.closest('[data-agent]');if(item)openDetail(item.dataset.agent);
});
document.addEventListener('keydown',event=>{
  if(event.key==='Enter' && event.target.matches('.attention-row')) openDetail(event.target.dataset.agent);
});
$('#searchAgents').addEventListener('input',renderAgentTable);
$('#riskFilter').addEventListener('change',renderAgentTable);
$('#newAgentBtn').addEventListener('click', async ()=>{
  $('#formError').textContent='';
  try { connections = await api('/api/connections'); } catch (_) { connections=[]; }
  const select=$('#agentConnection');
  select.innerHTML='<option value="">Standalone manual record</option>'+connections.map(c=>`<option value="${safe(c.id)}">${safe(c.label)}</option>`).join('');
  select.onchange=()=>{
    if(select.value){const c=connections.find(x=>x.id===select.value);if(c)$('#agentForm').elements.provider.value=c.provider;}
  };
  $('#registryMoreActions').open=false;
  $('#agentDialog').showModal();
});
$('#agentForm').addEventListener('submit',async e=>{
  e.preventDefault();const form=e.currentTarget;const data=Object.fromEntries(new FormData(form).entries());
  data.budget_usd=Number(data.budget_usd);data.sensitive_access=Boolean(data.sensitive_access);
  if(!data.owner_email) data.owner_email=null;
  if(!data.connection_id) data.connection_id=null;
  try {const agent=await api('/api/agents',{method:'POST',body:JSON.stringify(data)});form.reset();$('#agentDialog').close();showView('agents');await refresh();openDetail(agent.id);} catch(err){ $('#formError').textContent=err.message; }
});
async function openDetail(id){
  try {
    const a=await api(`/api/agents/${encodeURIComponent(id)}`);selectedAgent=id;
    $('#detailName').textContent=a.name;$('#detailDescription').textContent=a.description||'No description provided.';
    const meta=[['Provider',a.provider],['Technical owner',a.owner_email||'Unassigned'],['Business Owner',a.business_owner_name||'Not assigned'],['Cost center',a.cost_center||'Not set'],['Environment',a.environment],['Business approval',a.approval_status],['Last recorded activity',shortDate(a.last_seen)],['Monthly recorded spend',a.spend_observed===false ? 'Not tracked' : money(a.monthly_spend_usd)],['Monthly budget',money(a.budget_usd)],['Data source',a.source]];
    if(a.source==='discovered') meta.push(['Provider approval (metadata)',a.provider_approval_status||'Unknown']);
    if(a.source==='discovered') meta.push(['Provider ID',a.external_id],['Provider status',a.provider_status],['Last discovered',shortDate(a.discovery_last_seen)]);
    $('#detailContent').innerHTML=`<div class="detail-meta">${meta.map(([k,v])=>`<div class="meta-card"><small>${safe(k)}</small><strong>${safe(v)}</strong></div>`).join('')}</div><div class="detail-section"><h3>Advisory findings ${riskPill(a.risk_level)}</h3>${a.findings.length?a.findings.map(f=>`<div class="finding">${riskPill(f.severity)}<span><strong>${safe(f.title || f.code)}</strong><p>${safe(f.message)}</p><small>Evidence: ${safe(JSON.stringify(f.evidence || {}))}</small><p>Next step: ${safe(f.remediation || 'Review this finding.')}</p></span></div>`).join(''):'<p class="muted">No findings matched enabled rules. This is not a security certification; provider data may be incomplete.</p>'}</div>`;
    // Security references do not imply that an agent is vulnerable, and do not assign CVSS.
    const canDocumentCve=(currentIdentity?.capabilities||[]).includes('governance.remediate');
    $('#detailContent').insertAdjacentHTML('beforeend', `<div class="detail-section"><h3>Vulnerability references (CVE)</h3>
      <p class="provider-helper">Link a CVE to an identified software component. An ID alone is not proof of impact. Reported affected status is user-attested; CVSS scores are not yet enriched; open NVD for authoritative severity information.</p>
      <div id="vulnerabilityReferences">Loading linked vulnerabilities…</div>
      ${canDocumentCve?`<details><summary>Add a CVE reference</summary><form id="vulnerabilityForm" class="provider-form">
        <label>CVE ID<input name="cve_id" placeholder="CVE-2026-12345" required minlength="13" maxlength="32"></label>
        <label>Affected component<input name="component_name" placeholder="Library, MCP server, container image, or tool" required minlength="2"></label>
        <label>Observed component version<input name="component_version" placeholder="Version or digest; required for confirmed affected"></label>
        <label>Assessment <select name="assessment"><option value="under_review">Under review (not confirmed)</option><option value="affected">Affected — confirmed by evidence</option><option value="not_affected">Not affected — assessed</option></select></label>
        <label>Evidence reference<input name="evidence_source" maxlength="500" placeholder="Scanner/SBOM report ID or assessment reference"></label>
        <p class="provider-helper">Confirmed affected status requires a version/digest and evidence reference. CVSS is never estimated from the agent name.</p>
        <button type="submit" class="secondary-btn">Link CVE</button><div id="vulnerabilityError" class="error" role="alert"></div></form></details>`:''}
    </div>`);
    await renderVulnerabilityReferences(a.id);
    await renderGovernance(a);
    $('#usageAddBox').hidden = a.source==='discovered' || (currentIdentity && !(currentIdentity.capabilities||[]).includes('usage.record'));
    $('#usageError').textContent='';$('#usageForm').reset();$('#detailDialog').showModal();
  } catch(error) {alert(`Unable to open agent: ${error.message}`);}
}
async function renderVulnerabilityReferences(agentId){
  const node=$('#vulnerabilityReferences');if(!node)return;
  try {
    const links=await api(`/api/agents/${encodeURIComponent(agentId)}/vulnerabilities`);
    node.innerHTML=links.length?links.map(v=>`<div class="finding">
      <span class="tag">${safe(v.assessment.replaceAll('_',' '))}</span>
      <span><strong>${safe(v.cve_id)}</strong> · ${safe(v.component_name)} ${safe(v.component_version||'version unknown')}
      <p>Evidence: ${safe(v.evidence_source||'Not supplied')}</p>
      <small>CVSS: Not enriched by GAME</small>
      <p><a href="${safe(v.nvd_url)}" target="_blank" rel="noopener noreferrer">View official NVD record / CVSS →</a></p>
      </span></div>`).join(''):'<p class="muted">No CVE references linked. This does not mean the agent has been scanned or is vulnerability-free.</p>';
  } catch(err){node.textContent='Unable to load CVE references: '+err.message;}
}
$('#detailContent').addEventListener('submit',async e=>{
  if(e.target.id!=='vulnerabilityForm')return;
  e.preventDefault();
  const err=$('#vulnerabilityError');err.textContent='';
  const body=Object.fromEntries(new FormData(e.target).entries());
  try {
    await api(`/api/agents/${encodeURIComponent(selectedAgent)}/vulnerabilities`,{method:'POST',body:JSON.stringify(body)});
    $('#detailDialog').close();
    await refresh();
    openDetail(selectedAgent);
  }catch(error){err.textContent=error.message;}
});
$('#usageForm').addEventListener('submit',async e=>{
  e.preventDefault();if(!selectedAgent)return;
  const data=Object.fromEntries(new FormData(e.currentTarget).entries());
  try {await api('/api/usage',{method:'POST',body:JSON.stringify({agent_id:selectedAgent,cost_usd:Number(data.cost_usd),outcome:data.outcome})});$('#detailDialog').close();await refresh();openDetail(selectedAgent);} catch(error){ $('#usageError').textContent=error.message; }
});
let currentIdentity=null;
api('/api/me').then(me => {
  currentIdentity=me;
  $('#tenantIdentity').textContent=`${me.tenant_name} · ${me.display_role || me.role}`;
  $('#sidebarCompanyAccess').textContent=`v0.3.5 · ${me.tenant_name || 'Company'} Access`;
  const caps=new Set(me.capabilities || []);
  $('#usersNav').hidden=!caps.has('members.manage');
  $('#auditNav').hidden=!caps.has('audit.view');
  document.querySelector('.nav-item[data-view="trustGraph"]').hidden=!caps.has('agents.view');
  document.querySelector('[data-view="runtime"]').hidden=!caps.has('runtime.view');
  document.querySelector('[data-view="finops"]').hidden=!caps.has('finops.usage.view');
  document.querySelector('.finops-azure-section').hidden=!caps.has('finops.billing.view');
  $('#adminSection').hidden=!(caps.has('members.manage')||caps.has('audit.view'));
  $('#myPasswordLink').hidden=me.auth_mode!=='password';
  $('#logoutBtn').hidden=me.auth_mode!=='password';
  if(me.auth_mode==='password'){ $('#localUsersPanel').hidden=false; $('#oidcUsersPanel').hidden=true; }
  else { $('#localUsersPanel').hidden=true; $('#oidcUsersPanel').hidden=false; }
  if(window.location.hash==='#users' && !caps.has('members.manage')) showView('overview');
  if(window.location.hash==='#users' && caps.has('members.manage')) showView('users');
  if(window.location.hash==='#audit' && !caps.has('audit.view'))showView('overview');
  if(window.location.hash==='#audit' && caps.has('audit.view'))showView('audit');
  if(window.location.hash==='#trustGraph' && !caps.has('agents.view'))showView('overview');
  if(window.location.hash==='#runtime' && !caps.has('runtime.view'))showView('overview');
  if(window.location.hash==='#finops' && !caps.has('finops.usage.view'))showView('overview');
  if(window.location.hash==='#policies') refreshPolicies();
  $('#newAgentBtn').hidden=!caps.has('agents.register');
  $('#registryMoreActions').hidden=!caps.has('agents.register');
  $('#usageAddBox').hidden=!caps.has('usage.record');
  $('#connectionForm').parentElement.hidden=!caps.has('connections.manage');
})
  .catch(() => {$('#tenantIdentity').textContent='SIGN-IN REQUIRED';});
refresh();
const initialView = window.location.hash.substring(1);
if (pageDetails[initialView]) showView(initialView);
window.addEventListener('hashchange', () => {
  const view = window.location.hash.substring(1);
  if (pageDetails[view]) showView(view);
});

// Localhost development credential forms: backend encrypts submitted credentials at rest.
// No sensitive values in localStorage, connection metadata or frontend logs.
let catalog = [];
let connections = [];
let editingConnection = null;
const scopeByProvider = {
  custom_registry:[['registry_name','Private registry namespace','e.g. internal-platform']],
  github_inventory:[['organization','GitHub organization','Happili-platform']],
  atlassian_rovo_mcp:[['endpoint','Atlassian MCP endpoint','https://mcp.atlassian.com/v2/mcp']],
  microsoft_foundry:[['project_endpoint','Foundry project endpoint','https://resource.services.ai.azure.com/api/projects/project']],
  google_agent_engine:[['project_id','Google project ID','my-google-project'],['location','Google location','us-central1']],
  aws_agentcore:[['region','AWS region','us-east-1']],
  aws_bedrock_classic:[['region','AWS region','us-east-1']]
};
const authModesByProvider={
  custom_registry:[['push_oidc','Authenticated outbound push (OIDC)']],
  github_inventory:[['legacy','GitHub App PEM (encrypted; localhost only)']],
  atlassian_rovo_mcp:[['legacy','Service account API key (encrypted; localhost only)']],
  microsoft_foundry:[['legacy','Local development credentials'],['entra_shared_app','Shared SaaS Entra app (renewable tokens)']],
  google_agent_engine:[['legacy','Local development JSON / ADC'],['google_impersonate','Service account impersonation (renewable)']],
  aws_agentcore:[['legacy','Local development temporary credentials'],['aws_assume_role','Cross-account IAM role (renewable)']],
  aws_bedrock_classic:[['legacy','Local development temporary credentials'],['aws_assume_role','Cross-account IAM role (renewable)']]
};
function updateAuthFields(){
  const mode=$('#connectionAuthMode').value;
  $('#workloadFields').hidden=mode==='legacy';
  $('#awsRoleField').hidden=mode!=='aws_assume_role';
  $('#googleImpersonateField').hidden=mode!=='google_impersonate';
  $('#entraTenantField').hidden=mode!=='entra_shared_app';
  $('#githubCredentialsFields').hidden=!(mode==='legacy'&&$('#providerKind').value==='github_inventory');
  $('#atlassianCredentialsFields').hidden=!(mode==='legacy'&&$('#providerKind').value==='atlassian_rovo_mcp');
  $('#azureCredentialsFields').hidden=!(mode==='legacy'&&$('#providerKind').value==='microsoft_foundry');
  $('#awsCredentialsFields').hidden=!(mode==='legacy'&&$('#providerKind').value.startsWith('aws_'));
  $('#googleCredentialsFields').hidden=!(mode==='legacy'&&$('#providerKind').value==='google_agent_engine');
  const help={
    aws_assume_role:'Save this connection first to receive a unique External ID. Configure the customer IAM role trust policy with your SaaS source role ARN and this External ID, then Test Connection. No temporary session token is pasted.',
    google_impersonate:'Grant the GAME host workload principal Service Account Token Creator on this target service account, and grant the target account Agent Platform read permission. Host credentials must support ADC.',
    entra_shared_app:'Customer admin consents to your multi-tenant Entra application and assigns RBAC on their Foundry project. SaaS operator configures GAME_AZURE_CLIENT_ID and GAME_AZURE_CLIENT_SECRET on the host; no customer secret is saved.',
    push_oidc:'Customer-hosted collectors submit inventory metadata to POST /api/connections/{id}/ingest using their tenant-authorized OIDC bearer identity. No inbound network access to customer systems required.',
    legacy:'Local development only. Existing per-connection credentials will be retained unless changed.'
  };
  $('#workloadHelp').textContent=help[mode]||'';
}
function updateProviderFields(){
  const id=$('#providerKind').value;
  $('#scopeFields').innerHTML=(scopeByProvider[id]||[]).map(([k,label,placeholder])=>`<label>${safe(label)}<input name="${safe(k)}" placeholder="${safe(placeholder)}" required /></label>`).join('');
  const info=catalog.find(p=>p.id===id);
  $('#providerAuthHelp').textContent=info ? `${info.auth}. Scope: ${info.scope}.` : '';
  $('#connectionForm').elements.env_prefix.value= id==='microsoft_foundry'?'AC_FOUNDRY':id==='google_agent_engine'?'AC_GOOGLE':id==='custom_registry'?'AC_CUSTOM':id==='github_inventory'?'AC_GITHUB':id==='atlassian_rovo_mcp'?'AC_ATLASSIAN':'AC_AWS';
  $('#connectionAuthMode').innerHTML=(authModesByProvider[id]||[]).map(([mode,label])=>`<option value="${safe(mode)}">${safe(label)}</option>`).join('');
  $('#connectionAuthMode').value='legacy';
  updateAuthFields();
  // Credentials from a different provider must not linger in hidden form fields.
  const f=$('#connectionForm');
  if(id!=='microsoft_foundry') f.elements.azure_client_secret.value='';
  if(!['aws_agentcore','aws_bedrock_classic'].includes(id)) {
    f.elements.aws_secret_access_key.value=''; f.elements.aws_session_token.value='';
  }
  if(id!=='google_agent_engine') f.elements.google_service_account_json.value='';
  if(id!=='github_inventory'){f.elements.github_app_id.value='';f.elements.github_private_key_pem.value='';}
  if(id!=='atlassian_rovo_mcp')f.elements.atlassian_api_key.value='';
}
function resetConnectionForm(){
  editingConnection=null;
  const f=$('#connectionForm');
  f.reset();
  $('#providerKind').disabled=false;
  f.elements.aws_role_arn.value='';
  f.elements.google_impersonate_email.value='';
  f.elements.entra_customer_tenant_id.value='';
  f.elements.azure_tenant_id.value='';
  f.elements.azure_client_id.value='';
  f.elements.azure_client_secret.value='';
  f.elements.aws_access_key_id.value='';
  f.elements.aws_secret_access_key.value='';
  f.elements.aws_session_token.value='';
  f.elements.aws_expires_at.value='';
  f.elements.google_service_account_json.value='';
  f.elements.github_app_id.value=''; f.elements.github_private_key_pem.value=''; f.elements.atlassian_api_key.value='';
  $('#connectionFormTitle').textContent='Onboard a provider';
  $('#connectionSubmit').textContent='Add provider connection';
  $('#cancelConnectionEdit').hidden=true;
  $('#connectionError').textContent='';
  $('#editNote').hidden=true;
  updateProviderFields();
}
function beginConnectionEdit(id){
  const c=connections.find(x=>x.id===id);
  if(!c){$('#connectionList').textContent='Connection changed. Refresh the page and try again.';return;}
  editingConnection=c;
  const f=$('#connectionForm');
  $('#providerKind').value=c.provider;
  updateProviderFields();
  $('#connectionAuthMode').value=c.auth_mode||'legacy';
  updateAuthFields();
  f.elements.aws_role_arn.value=c.auth_config?.role_arn||'';
  f.elements.google_impersonate_email.value=c.auth_config?.service_account_email||'';
  f.elements.entra_customer_tenant_id.value=c.auth_config?.tenant_id||'';
  $('#providerKind').disabled=true; // Existing provider identity is immutable.
  f.elements.label.value=c.label;
  f.elements.env_prefix.value=c.env_prefix;
  for(const [key] of (scopeByProvider[c.provider]||[])) f.elements[key].value=c.scope[key]||'';
  // NEVER populate password fields from the backend.
  f.elements.azure_tenant_id.value='';
  f.elements.azure_client_id.value='';
  f.elements.azure_client_secret.value='';
  f.elements.aws_access_key_id.value='';
  f.elements.aws_secret_access_key.value='';
  f.elements.aws_session_token.value='';
  f.elements.aws_expires_at.value='';
  f.elements.google_service_account_json.value='';
  f.elements.github_app_id.value=''; f.elements.github_private_key_pem.value=''; f.elements.atlassian_api_key.value='';
  $('#connectionFormTitle').textContent='Edit provider connection';
  $('#connectionSubmit').textContent='Save changes';
  $('#cancelConnectionEdit').hidden=false;
  $('#connectionError').textContent='';
  $('#editNote').hidden=false;
  $('#connectionForm').scrollIntoView({behavior:'smooth',block:'start'});
  f.elements.label.focus();
}
async function initProviders(){
  try{
    catalog=await api('/api/providers');
    $('#providerKind').innerHTML=catalog.filter(p=>p.status==='implemented').map(p=>`<option value="${safe(p.id)}">${safe(p.name)}</option>`).join('');
    $('#catalogList').innerHTML=catalog.map(p=>`<div class="catalog-item"><strong>${safe(p.name)}</strong><span class="catalog-status">${p.id==='custom_registry'?'Push ingestion available':p.status==='implemented'?'Discovery available':'Planned'}</span><small>${safe(p.scope)}</small></div>`).join('');
    updateProviderFields();
  }catch(err){$('#connectionError').textContent=err.message;}
}
$('#providerKind').addEventListener('change',updateProviderFields);
$('#connectionAuthMode').addEventListener('change',updateAuthFields);
$('#cancelConnectionEdit').addEventListener('click',resetConnectionForm);
$('#connectionForm').addEventListener('submit',async event=>{
  event.preventDefault();$('#connectionError').textContent='';
  const f=event.currentTarget, data=Object.fromEntries(new FormData(f).entries());
  // A disabled provider selector is excluded from FormData. Existing provider is immutable.
  data.provider=editingConnection?.provider || $('#providerKind').value;
  const scope={};for(const [key] of (scopeByProvider[data.provider]||[]))scope[key]=data[key];
  const mode=$('#connectionAuthMode').value;
  const authConfig={};
  if(mode==='aws_assume_role')authConfig.role_arn=data.aws_role_arn?.trim();
  if(mode==='google_impersonate')authConfig.service_account_email=data.google_impersonate_email?.trim();
  if(mode==='entra_shared_app')authConfig.tenant_id=data.entra_customer_tenant_id?.trim();
  const payload={label:data.label,env_prefix:data.env_prefix,scope,auth_mode:mode,auth_config:authConfig};
  const azureValues=[data.azure_tenant_id?.trim(),data.azure_client_id?.trim(),data.azure_client_secret].filter(Boolean);
  const awsValues=[data.aws_access_key_id?.trim(),data.aws_secret_access_key,data.aws_session_token?.trim()].filter(Boolean);
  const ghValues=[data.github_app_id?.trim(),data.github_private_key_pem?.trim()].filter(Boolean);
  if(data.provider==='github_inventory' && ghValues.length===1){$('#connectionError').textContent='Provide both the numeric GitHub App ID and private key PEM.';return;}
  if(mode==='legacy' && data.provider==='microsoft_foundry' && azureValues.length>0 && azureValues.length!==3){
    $('#connectionError').textContent='Enter all three Microsoft credential fields, or leave all blank.';return;
  }
  if(mode==='legacy' && ['aws_agentcore','aws_bedrock_classic'].includes(data.provider) && awsValues.length>0 && awsValues.length!==3){
    $('#connectionError').textContent='Enter Access Key ID, Secret Access Key and Session Token together, or leave all blank.';return;
  }
  let connectionId = editingConnection?.id;
  try{
    if(editingConnection){
      const changedScope=Object.keys(scope).some(k=>scope[k]!==editingConnection.scope[k]);
      const changedAuth=mode!==(editingConnection.auth_mode||'legacy')||
        Object.entries(authConfig).some(([k,v])=>v!==editingConnection.auth_config?.[k])||
        data.env_prefix!==editingConnection.env_prefix;
      const changedTarget=changedScope||changedAuth;
      if(changedTarget && !confirm('Changing the project, cloud account, or authorization identity can invalidate existing discovered records. Clear the old inventory if required?')) return;
      await api(`/api/connections/${encodeURIComponent(connectionId)}`,{method:'PATCH',body:JSON.stringify({...payload,clear_inventory_on_scope_change:changedTarget})});
    }else{
      const created = await api('/api/connections',{method:'POST',body:JSON.stringify({...payload,provider:data.provider})});
      connectionId=created.id;
    }
    if(data.provider==='github_inventory' && ghValues.length===2){
      await api(`/api/connections/${encodeURIComponent(connectionId)}/credentials`,{method:'PUT',body:JSON.stringify({app_id:data.github_app_id.trim(),private_key_pem:data.github_private_key_pem.trim()})});
    } else if(data.provider==='atlassian_rovo_mcp' && data.atlassian_api_key?.trim()){
      await api(`/api/connections/${encodeURIComponent(connectionId)}/credentials`,{method:'PUT',body:JSON.stringify({api_key:data.atlassian_api_key.trim()})});
    } else if(mode==='legacy' && data.provider==='microsoft_foundry' && azureValues.length===3){
      await api(`/api/connections/${encodeURIComponent(connectionId)}/credentials`,{method:'PUT',body:JSON.stringify({
        tenant_id:data.azure_tenant_id.trim(),client_id:data.azure_client_id.trim(),client_secret:data.azure_client_secret
      })});
    } else if(mode==='legacy' && ['aws_agentcore','aws_bedrock_classic'].includes(data.provider) && awsValues.length===3){
      await api(`/api/connections/${encodeURIComponent(connectionId)}/credentials`,{method:'PUT',body:JSON.stringify({
        access_key_id:data.aws_access_key_id.trim(),secret_access_key:data.aws_secret_access_key,session_token:data.aws_session_token.trim(),
        ...(data.aws_expires_at ? {expires_at:new Date(data.aws_expires_at).toISOString()} : {})
      })});
    } else if(mode==='legacy' && data.provider==='google_agent_engine' && data.google_service_account_json?.trim()){
      await api(`/api/connections/${encodeURIComponent(connectionId)}/credentials`,{method:'PUT',body:JSON.stringify({
        service_account_json:data.google_service_account_json.trim()
      })});
    }
    resetConnectionForm();
    await refreshConnections();
    await refresh();
  }catch(err){
    // Clear the secret from the live DOM, even when a request fails.
    f.elements.azure_client_secret.value='';
    f.elements.aws_secret_access_key.value='';
    f.elements.aws_session_token.value='';
  f.elements.aws_expires_at.value='';
    f.elements.google_service_account_json.value='';
  f.elements.github_app_id.value=''; f.elements.github_private_key_pem.value=''; f.elements.atlassian_api_key.value='';
    $('#connectionError').textContent=err.message+' (If the connection was saved, use Edit to retry credentials.)';
    await refreshConnections();
  }
});
async function refreshConnections(){
  try{
    connections=await api('/api/connections');
    $('#connectionList').innerHTML=connections.length ? connections.map(c=>{
      const provider=catalog.find(p=>p.id===c.provider)?.name||c.provider;
      const scopeText=Object.entries(c.scope).map(([key,value])=>`${key}: ${value}`).join(' · ');
      const authText = c.credential_source==='encrypted' ?
        (c.credential_status==='expired'?'Encrypted credentials — expired':`Encrypted credentials — saved${c.credential_status==='expiration_unknown' && ['aws_agentcore','aws_bedrock_classic'].includes(c.provider)?' (AWS expiration not recorded)':''}`) :
        c.credential_source==='vault_unavailable'?'Encrypted credentials — VAULT KEY UNAVAILABLE':
        c.credential_source==='push_oidc'?'Authenticated registry push':
        c.credential_source==='workload_identity'?'Renewable workload identity (verify access)':
        c.credential_source==='environment'?'Host environment configured':
        c.credential_source==='managed_identity'?'Managed identity':
        c.credential_source==='external'?'SDK chain (not verified)':'Not configured';
      const workloadInfo=c.auth_mode==='aws_assume_role'?` · Role: ${c.auth_config.role_arn} · External ID: ${c.auth_config.external_id}`:c.auth_mode==='google_impersonate'?` · Impersonate: ${c.auth_config.service_account_email}`:c.auth_mode==='entra_shared_app'?` · Customer tenant: ${c.auth_config.tenant_id}`:'';
      const expText=c.credential_expires_at?` · Expires: ${new Date(c.credential_expires_at).toLocaleString()}`:'';
      const inboundInfo=c.provider==='custom_registry'?` · Push endpoint: /api/connections/${safe(c.id)}/ingest`:'';
      const canManage=!currentIdentity || (currentIdentity.capabilities||[]).includes('connections.manage');
      const canRemove=!currentIdentity || (currentIdentity.capabilities||[]).includes('members.manage');
      return `<div class="connection-item"><strong>${safe(c.label)}</strong><small>${safe(provider)}</small><small>${safe(scopeText)}</small><small>Credential prefix: ${safe(c.env_prefix)} · Authentication: ${safe(authText)}${safe(workloadInfo)}${inboundInfo}${safe(expText)} · Last sync: ${safe(shortDate(c.last_synced_at))}</small>${c.last_error?`<small class="error">Last error: ${safe(c.last_error)}</small>`:''}<div class="connection-actions">${canManage?`<button type="button" class="secondary-btn" data-edit="${safe(c.id)}">Edit / credentials</button>${['encrypted','vault_unavailable'].includes(c.credential_source)?`<button type="button" class="secondary-btn" data-clear-creds="${safe(c.id)}">Clear saved credentials</button>`:''}${c.provider==='custom_registry'?'':`<button type="button" class="secondary-btn" data-test="${safe(c.id)}">Test connection</button><button type="button" class="secondary-btn" data-sync="${safe(c.id)}">Discover now</button>`}${canRemove?`<button type="button" class="danger-outline" data-remove="${safe(c.id)}">Remove</button>`:``}`:``}</div></div>`;
    }).join('') : '<p class="muted">No provider connections are registered yet. Choose a provider and complete the onboarding form to add one.</p>';
  }catch(err){$('#connectionList').textContent=`Could not load connections: ${err.message}`;}
}
document.addEventListener('click',async e=>{
  const edit=e.target.closest('[data-edit]');
  if(edit){beginConnectionEdit(edit.dataset.edit);return;}
  const clear=e.target.closest('[data-clear-creds]');
  if(clear){
    if(!confirm('Permanently delete the encrypted credentials for this connection? This cannot be undone.'))return;
    try{await api(`/api/connections/${encodeURIComponent(clear.dataset.clearCreds)}/credentials`,{method:'DELETE'});await refreshConnections();}
    catch(err){alert('Unable to clear credentials: '+err.message);}
    return;
  }
  const test=e.target.closest('[data-test]');
  if(test){
    test.disabled=true;test.textContent='Testing…';
    try {
      const result=await api(`/api/connections/${encodeURIComponent(test.dataset.test)}/test`,{method:'POST'});
      alert(result.inventory_counts?`Connection successful: ${Object.entries(result.inventory_counts).map(([k,v])=>`${v} ${k}`).join(', ')}. No inventory saved.`:`Connection successful: ${result.visible_agents} agent(s) visible. No inventory records changed.`);
    } catch(err){alert('Connection test failed: '+err.message);}
    finally{await refreshConnections();}
    return;
  }
  const remove=e.target.closest('[data-remove]');
  if(remove){
    const id=remove.dataset.remove;
    const c=connections.find(x=>x.id===id);
    if(!c)return;
    if(!confirm(`Remove "${c.label}" and all its locally discovered agent records? This does not change or delete agents in the provider.`))return;
    remove.disabled=true;
    try{
      await api(`/api/connections/${encodeURIComponent(id)}?remove_inventory=true`,{method:'DELETE'});
      if(editingConnection?.id===id)resetConnectionForm();
      await refreshConnections();await refresh();
    }catch(err){await refreshConnections();alert('Unable to remove connection: '+err.message);}
    return;
  }
  const button=e.target.closest('[data-sync]');if(!button)return;
  const id=button.dataset.sync;button.disabled=true;button.textContent='Discovering…';
  try{
    const result=await api(`/api/connections/${encodeURIComponent(id)}/discover`,{method:'POST'});
    await refreshConnections();await refresh();
    alert(result.inventory_counts?`Inventory completed: ${Object.entries(result.inventory_counts).map(([k,v])=>`${v} ${k}`).join(', ')}. No agent usage implied.`:`Discovery completed: ${result.discovered} agents found. Note: this is inventory only, not usage or cost telemetry.`);
  }catch(err){await refreshConnections();alert('Discovery failed: '+err.message);}
});
initProviders();


// Single-company RBAC: the server returns the authoritative inherited capabilities.
let rolesCatalog=null;
let memberRows=[];
function chosenMemberRole(){return rolesCatalog?.roles.find(r=>r.id===$('#memberRole').value);}
function renderInheritedPermissions(){
  const role=chosenMemberRole(); if(!role)return;
  $('#inheritedRoles').innerHTML=rolesCatalog.roles.map(r=>`<label class="rbac-check"><input type="checkbox" disabled ${role.effective_roles.includes(r.id)?'checked':''} /> <span>${safe(r.label)}</span></label>`).join('');
  $('#effectiveCapabilities').innerHTML=rolesCatalog.capabilities.map(c=>`<label class="rbac-check"><input type="checkbox" disabled ${role.capabilities.includes(c.id)?'checked':''} /> <span>${safe(c.label)}</span></label>`).join('');
  const scope=$('#memberScope');
  if(role.id==='admin' || role.id==='auditor'){
    scope.value='all';scope.disabled=true;
  }else{scope.disabled=false;}
  $('#scopeChoices').hidden=scope.value==='all';
}
function renderMemberScopes(){
  $('#memberConnectionChoices').innerHTML=connections.length?connections.map(c=>`<label class="rbac-check"><input type="checkbox" name="member_connection" value="${safe(c.id)}"> ${safe(c.label)}</label>`).join(''):'<p class="muted">No connections yet.</p>';
  $('#memberAgentChoices').innerHTML=agents.length?agents.map(a=>`<label class="rbac-check"><input type="checkbox" name="member_agent" value="${safe(a.id)}"> ${safe(a.name)}</label>`).join(''):'<p class="muted">No agents yet.</p>';
}
function resetMembershipForm(){
  $('#membershipForm').reset();$('#membershipError').textContent='';
  $('#membershipForm').elements.subject.readOnly=false;
  $('#membershipForm').elements.issuer.readOnly=false;
  renderInheritedPermissions();
}
async function refreshMembers(){
  if(currentIdentity?.auth_mode==='password') return refreshLocalUsers();
  try{
    [rolesCatalog,memberRows,connections,agents] = await Promise.all([
      api('/api/rbac/catalog'),api('/api/members'),api('/api/connections'),api('/api/agents')]);
    const order=['admin','provider_admin','agent_owner','business_owner','auditor','viewer'];
    const options=rolesCatalog.roles.toSorted((a,b)=>order.indexOf(a.id)-order.indexOf(b.id)).map(r=>`<option value="${safe(r.id)}">${safe(r.label)}</option>`).join('');
    if($('#memberRole').innerHTML!==options)$('#memberRole').innerHTML=options;
    renderMemberScopes();renderInheritedPermissions();
    $('#memberList').innerHTML=memberRows.length?memberRows.map(m=>{
      const normalized={'tenant_admin':'admin','connection_admin':'provider_admin','analyst':'agent_owner'}[m.role]||m.role;
      const label=rolesCatalog.roles.find(r=>r.id===normalized)?.label||m.role;
      const scope=m.scope?.kind==='all'?'Company-wide':`${(m.scope?.connection_ids||[]).length} connections · ${(m.scope?.agent_ids||[]).length} agents`;
      return `<div class="connection-item"><strong>${safe(m.subject)}</strong><small>${safe(m.issuer)}</small><small>${safe(label)} · ${safe(scope)} · ${m.active?'Active':'Inactive'}</small><div class="connection-actions"><button type="button" class="secondary-btn" data-member-edit="${safe(m.subject)}">Edit</button>${m.active?`<button type="button" class="danger-outline" data-member-revoke="${safe(m.subject)}">Revoke</button>`:''}</div></div>`;
    }).join(''):'<p class="muted">No company users configured. Add the first identity on the left.</p>';
  }catch(err){$('#membershipError').textContent=err.message;}
}
$('#memberRole').addEventListener('change', ()=>{
  if(!['admin','auditor'].includes($('#memberRole').value))$('#memberScope').value='selected';
  renderInheritedPermissions();
});
$('#memberScope').addEventListener('change', ()=>{$('#scopeChoices').hidden=$('#memberScope').value==='all';});
$('#cancelMemberEdit').addEventListener('click',resetMembershipForm);
$('#membershipForm').addEventListener('submit',async e=>{
  e.preventDefault();$('#membershipError').textContent='';
  const data=new FormData(e.currentTarget);
  const enforcedAll=['admin','auditor'].includes(data.get('role'));
  const scope=(enforcedAll || data.get('scope_kind')==='all')?{kind:'all'}:{kind:'selected',connection_ids:data.getAll('member_connection'),agent_ids:data.getAll('member_agent')};
  try{
    await api('/api/members',{method:'POST',body:JSON.stringify({issuer:String(data.get('issuer')).trim(),subject:String(data.get('subject')).trim(),role:data.get('role'),scope})});
    resetMembershipForm();await refreshMembers();
  }catch(err){$('#membershipError').textContent=err.message;}
});
document.addEventListener('click',async e=>{
  const edit=e.target.closest('[data-member-edit]');
  if(edit){
    const m=memberRows.find(x=>x.subject===edit.dataset.memberEdit);if(!m)return;
    const f=$('#membershipForm');f.elements.issuer.value=m.issuer;f.elements.subject.value=m.subject;
    f.elements.role.value=rolesCatalog.roles.find(r=>r.id===m.role)?.id||({'tenant_admin':'admin','connection_admin':'provider_admin','analyst':'agent_owner'}[m.role]||'viewer');
    renderInheritedPermissions();if(!['admin','auditor'].includes(f.elements.role.value))$('#memberScope').value=m.scope?.kind||'selected';
    $('#scopeChoices').hidden=$('#memberScope').value==='all';
    document.querySelectorAll('input[name="member_connection"]').forEach(x=>{x.checked=(m.scope?.connection_ids||[]).includes(x.value);});
    document.querySelectorAll('input[name="member_agent"]').forEach(x=>{x.checked=(m.scope?.agent_ids||[]).includes(x.value);});
    f.elements.issuer.readOnly=true;f.elements.subject.readOnly=true;f.scrollIntoView({behavior:'smooth'});return;
  }
  const revoke=e.target.closest('[data-member-revoke]');
  if(revoke){
    const m=memberRows.find(x=>x.subject===revoke.dataset.memberRevoke);if(!m||!confirm(`Revoke access for ${m.subject}?`))return;
    try{await api('/api/members/revoke',{method:'POST',body:JSON.stringify({issuer:m.issuer,subject:m.subject})});await refreshMembers();}
    catch(err){alert('Could not revoke: '+err.message);}
  }
});


// Local password accounts (Admin-only UI; API authorizes every action).
let localUserRows=[];
let editingLocalId=null;
let localRoleCatalog=null;
async function localMemberCatalog(){
  localRoleCatalog=localRoleCatalog||await api('/api/rbac/catalog');
  const dropdown=$('#localRole');
  if(!dropdown.options.length){
    const roles=['admin','provider_admin','agent_owner','business_owner','auditor','viewer'];
    dropdown.innerHTML=roles.map(id=>{const r=localRoleCatalog.roles.find(x=>x.id===id);return `<option value="${safe(id)}">${safe(r.label)}</option>`;}).join('');
    dropdown.value='viewer';
  }
}
let selectedLocalCapabilities=null;
function renderLocalInherited(){
  if(!localRoleCatalog)return;
  const role=$('#localRole').value,r=localRoleCatalog.roles.find(x=>x.id===role);
  if(!r)return;
  if(!selectedLocalCapabilities) selectedLocalCapabilities=new Set(r.capabilities);
  $('#localEffectiveCaps').innerHTML=localRoleCatalog.capabilities
    .filter(c=>r.capabilities.includes(c.id))
    .map(c=>`<label class="rbac-check"><input type="checkbox" class="local-capability" value="${safe(c.id)}" ${selectedLocalCapabilities.has(c.id)?'checked':''} ${!editingLocalId||c.id==='members.manage'&&role==='admin'?'disabled':''} /> <span>${safe(c.label)}</span></label>`).join('');
  const fixed=['admin','auditor','business_owner'].includes(role);
  if(fixed)$('#localScope').value=role==='business_owner'?'selected':'all';
  $('#localScope').disabled=fixed;
  $('#localScopeChoices').hidden=$('#localScope').value==='all';
}
async function loadCompanySettings(){
  const msg=$('#companySettingsMessage');
  try{
    const settings=await api('/api/company/settings');
    $('#companyNameInput').value=settings.company_name;
    $('#companyAccessPreview').textContent=`${settings.company_name} Access`;
    msg.textContent='';
  }catch(error){msg.textContent=error.message;}
}
$('#companyNameInput').addEventListener('input',event=>{
  $('#companyAccessPreview').textContent=`${event.target.value.trim() || 'Company'} Access`;
});
$('#companySettingsForm').addEventListener('submit',async event=>{
  event.preventDefault();
  const msg=$('#companySettingsMessage');msg.textContent='';
  const button=event.currentTarget.querySelector('button[type="submit"]');
  button.disabled=true;
  try{
    const saved=await api('/api/company/settings',{
      method:'PATCH',body:JSON.stringify({company_name:$('#companyNameInput').value.trim()})
    });
    $('#companyNameInput').value=saved.company_name;
    $('#companyAccessPreview').textContent=`${saved.company_name} Access`;
    $('#sidebarCompanyAccess').textContent=`v0.3.5 · ${saved.company_name} Access`;
    if(currentIdentity){currentIdentity.tenant_name=saved.company_name;
      $('#tenantIdentity').textContent=`${saved.company_name} · ${currentIdentity.display_role || currentIdentity.role}`;}
    msg.textContent='Company name saved. The updated name will appear on the next sign-in.';
  }catch(error){msg.textContent=error.message;}
  finally{button.disabled=false;}
});
async function refreshLocalUsers(){
  try{
    await localMemberCatalog();
    [localUserRows,connections,agents]=await Promise.all([api('/api/local-users'),api('/api/connections'),api('/api/agents')]);
    $('#localConnectionChoices').innerHTML=connections.map(c=>`<label><input type="checkbox" name="local_connection" value="${safe(c.id)}">${safe(c.label)}</label>`).join('')||'<small>No connections yet</small>';
    $('#localAgentChoices').innerHTML=agents.map(a=>`<label><input type="checkbox" name="local_agent" value="${safe(a.id)}">${safe(a.name)}</label>`).join('')||'<small>No agents yet</small>';
    renderLocalInherited();
    $('#localUserList').innerHTML=localUserRows.length?localUserRows.map(u=>{
      const label=localRoleCatalog.roles.find(x=>x.id===u.role)?.label||u.role;
      const scope=u.scope?.kind==='all'?'Entire company':`${(u.scope?.connection_ids||[]).length} connections · ${(u.scope?.agent_ids||[]).length} agents`;
      return `<div class="connection-item"><strong>${safe(u.display_name||u.username)}</strong><small>${safe(u.username)} · ${safe(u.email||'No email')}</small><small>${safe(label)} · ${safe(scope)}</small><small>${u.active?'Active':'Disabled'} ${u.must_change_password?'· Password change required':''}</small>
      <div class="connection-actions"><button class="secondary-btn" data-local-edit="${safe(u.id)}">Edit</button><button class="secondary-btn" data-local-reset="${safe(u.id)}">Reset password</button><button class="${u.active?'danger-outline':'secondary-btn'}" data-local-toggle="${safe(u.id)}">${u.active?'Disable':'Enable'}</button></div></div>`;
    }).join(''):'<p class="muted">No local accounts yet. Create an Admin using the bootstrap script first.</p>';
  }catch(error){$('#localUserError').textContent=error.message;}
}
function resetLocalForm(){
  editingLocalId=null;const form=$('#localUserForm');form.reset();
  form.elements.username.readOnly=false;
  $('#initialPasswordLabel').hidden=false;
  form.elements.initial_password.required=true;
  $('#localSaveBtn').textContent='Create user';
  $('#localUserError').textContent='';
  selectedLocalCapabilities=null;
  renderLocalInherited();
}
$('#localRole').addEventListener('change',()=>{selectedLocalCapabilities=null;renderLocalInherited();});
$('#localEffectiveCaps').addEventListener('change',event=>{
  if(!event.target.matches('.local-capability')||!editingLocalId)return;
  const key=event.target.value,catalog=localRoleCatalog.capabilities;
  const implies=(cap,visited=new Set())=>{if(visited.has(cap))return visited;visited.add(cap);
    (catalog.find(c=>c.id===cap)?.implies||[]).forEach(x=>implies(x,visited));return visited;};
  if(event.target.checked){
    for(const dep of implies(key))selectedLocalCapabilities.add(dep);
  }else{
    selectedLocalCapabilities.delete(key);
    // Revoke permissions that depend on the unchecked prerequisite.
    let changed=true;while(changed){changed=false;
      for(const cap of [...selectedLocalCapabilities]){if([...implies(cap)].some(x=>!selectedLocalCapabilities.has(x))){selectedLocalCapabilities.delete(cap);changed=true;}}
    }
  }
  renderLocalInherited();
});
$('#localScope').addEventListener('change',renderLocalInherited);
$('#localCancel').addEventListener('click',resetLocalForm);
$('#localUserForm').addEventListener('submit',async e=>{
  e.preventDefault();$('#localUserError').textContent='';
  const f=e.currentTarget,data=new FormData(f);
  const role=data.get('role');
  const scope= (['admin','auditor'].includes(role)||(role!=='business_owner'&&data.get('scope_kind')==='all'))?{kind:'all'}:{kind:'selected',connection_ids:data.getAll('local_connection'),agent_ids:data.getAll('local_agent')};
  const payload={display_name:String(data.get('display_name')||''),email:String(data.get('email')||''),role,scope};
  if(editingLocalId)payload.capabilities=[...selectedLocalCapabilities];
  if(!editingLocalId){payload.username=String(data.get('username')||'');payload.initial_password=String(data.get('initial_password')||'');}
  try{
    await api(editingLocalId?`/api/local-users/${encodeURIComponent(editingLocalId)}`:'/api/local-users',
      {method:editingLocalId?'PATCH':'POST',body:JSON.stringify(payload)});
    resetLocalForm();await refreshLocalUsers();
  }catch(err){$('#localUserError').textContent=err.message;}
});
document.addEventListener('click',async e=>{
  const edit=e.target.closest('[data-local-edit]');
  if(edit){
    const u=localUserRows.find(x=>x.id===edit.dataset.localEdit);if(!u)return;
    editingLocalId=u.id;const f=$('#localUserForm');
    f.elements.username.value=u.username;f.elements.username.readOnly=true;
    f.elements.display_name.value=u.display_name||'';f.elements.email.value=u.email||'';
    f.elements.role.value=u.role;
    selectedLocalCapabilities=new Set(u.capabilities||localRoleCatalog.roles.find(r=>r.id===u.role)?.capabilities||[]);
    $('#initialPasswordLabel').hidden=true;f.elements.initial_password.required=false;f.elements.initial_password.value='';
    $('#localScope').value=u.scope?.kind||'selected';
    renderLocalInherited();
    document.querySelectorAll('input[name="local_connection"]').forEach(x=>x.checked=(u.scope?.connection_ids||[]).includes(x.value));
    document.querySelectorAll('input[name="local_agent"]').forEach(x=>x.checked=(u.scope?.agent_ids||[]).includes(x.value));
    $('#localSaveBtn').textContent='Save changes';f.scrollIntoView({behavior:'smooth'});return;
  }
  const toggle=e.target.closest('[data-local-toggle]');
  if(toggle){const u=localUserRows.find(x=>x.id===toggle.dataset.localToggle);if(!u||!confirm(`${u.active?'Disable':'Enable'} ${u.username}?`))return;
    try{await api(`/api/local-users/${encodeURIComponent(u.id)}`,{method:'PATCH',body:JSON.stringify({active:!u.active})});await refreshLocalUsers();}
    catch(err){alert(err.message);}return;
  }
  const reset=e.target.closest('[data-local-reset]');
  if(reset){const u=localUserRows.find(x=>x.id===reset.dataset.localReset);if(!u)return;
    resettingLocalId=u.id;$('#adminResetHelp').textContent=`Reset password for ${u.username}. The next login will require a change.`;
    $('#adminResetError').textContent='';$('#adminResetForm').reset();$('#adminResetDialog').showModal();return;
  }
});
$('#logoutBtn').addEventListener('click',async()=>{
  try{await api('/api/auth/logout',{method:'POST'});}finally{location.replace('/login');}
});

let resettingLocalId=null;
$('#adminResetForm').addEventListener('submit',async e=>{
  e.preventDefault();const f=e.currentTarget,err=$('#adminResetError');err.textContent='';
  if(f.elements.temporary_password.value!==f.elements.confirm_password.value){err.textContent='Passwords do not match';return;}
  try{await api(`/api/local-users/${encodeURIComponent(resettingLocalId)}/reset-password`,{method:'POST',
    body:JSON.stringify({temporary_password:f.elements.temporary_password.value})});
    f.reset();$('#adminResetDialog').close();resettingLocalId=null;await refreshLocalUsers();}
  catch(ex){err.textContent=ex.message;}
});
$('#adminResetDialog').addEventListener('close',()=>{$('#adminResetForm').reset();resettingLocalId=null;});

// Business approval is a separate sign-off; technical Admin never sees Approve/Reject actions.
let governanceCurrent=null;
async function renderGovernance(a){
  governanceCurrent=a;
  const caps=new Set(currentIdentity?.capabilities||[]);
  const canAssign=caps.has('agents.owner.assign');
  const canSubmit=caps.has('agents.submit') && !!a.business_owner_user_id && ['not_reviewed','rejected'].includes(a.approval_status);
  const canDecide=caps.has('agents.approve') && a.approval_status==='pending' &&
    currentIdentity?.subject===`local-user:${a.business_owner_user_id}`;
  $('#governanceSummary').innerHTML=`<div class="governance-summary"><span>Accountable owner: <strong>${safe(a.business_owner_name||'Not assigned')}</strong></span><span>Approval: <strong>${safe(a.approval_status)}</strong></span><span>Requested budget: <strong>${money(a.approval_requested_budget_usd??a.budget_usd??0)}</strong></span><span>Cost center: <strong>${safe(a.approval_requested_cost_center||a.cost_center||'Not assigned')}</strong></span></div>`+
    (a.approval_justification?`<p><strong>Business justification:</strong> ${safe(a.approval_justification)}</p>`:'')+
    (a.approval_reason?`<p><strong>Decision reason:</strong> ${safe(a.approval_reason)}</p>`:'');
  $('#businessOwnerForm').hidden=!canAssign;
  $('#approvalRequestForm').hidden=!canSubmit;
  if(canSubmit){$('#approvalBudget').value=a.budget_usd??0;$('#approvalCostCenter').value=a.cost_center||'';}
  $('#approvalDecisionForm').hidden=!canDecide;
  $('#governanceError').textContent='';
  if(canAssign){
    try{
      const owners=await api('/api/business-owners');
      $('#businessOwnerSelect').innerHTML='<option value="">Choose a Business Owner</option>'+owners.map(u=>`<option value="${safe(u.id)}">${safe(u.display_name||u.username)} (${safe(u.username)})</option>`).join('');
      $('#businessOwnerSelect').value=a.business_owner_user_id||'';
    }catch(error){$('#governanceError').textContent=error.message;}
  }
}
async function reloadGovernance(){
  await refresh();
  if(selectedAgent){const a=await api(`/api/agents/${encodeURIComponent(selectedAgent)}`);await renderGovernance(a);} 
}
$('#businessOwnerForm').addEventListener('submit',async e=>{
  e.preventDefault();if(!selectedAgent)return;
  const id=$('#businessOwnerSelect').value;if(!id)return;
  if(governanceCurrent?.approval_status==='approved' && !confirm('Changing the Business Owner resets the current business approval. Continue?'))return;
  try{await api(`/api/agents/${encodeURIComponent(selectedAgent)}/business-owner`,{method:'POST',body:JSON.stringify({owner_user_id:id})});await reloadGovernance();}
  catch(err){$('#governanceError').textContent=err.message;}
});
$('#approvalRequestForm').addEventListener('submit',async e=>{
  e.preventDefault();if(!selectedAgent)return;
  try{await api(`/api/agents/${encodeURIComponent(selectedAgent)}/approval-request`,{method:'POST',body:JSON.stringify({justification:$('#approvalJustification').value.trim(),requested_budget_usd:Number($('#approvalBudget').value),cost_center:$('#approvalCostCenter').value.trim()})});$('#approvalJustification').value='';await reloadGovernance();}
  catch(err){$('#governanceError').textContent=err.message;}
});
$('#approvalDecisionForm').addEventListener('click',async e=>{
  const btn=e.target.closest('[data-decision]');if(!btn||!selectedAgent)return;
  const reason=$('#approvalDecisionReason').value.trim();
  if(reason.length<10){$('#governanceError').textContent='Enter at least 10 characters of decision justification.';return;}
  const decision=btn.dataset.decision;
  try{await api(`/api/agents/${encodeURIComponent(selectedAgent)}/approval-decision`,{method:'POST',body:JSON.stringify({decision,reason})});$('#approvalDecisionReason').value='';await reloadGovernance();}
  catch(err){$('#governanceError').textContent=err.message;}
});

let auditRows=[];
function renderAuditRows(){
  const query=$('#auditSearch').value.trim().toLowerCase(),type=$('#auditType').value;
  const rows=auditRows.filter(r=>(!type||r.operation.startsWith(type)) &&
    (!query||[r.operation,r.actor,r.resource_id,r.details_json].some(v=>String(v||'').toLowerCase().includes(query))));
  $('#auditTable').innerHTML=rows.map(r=>{
    let extra='';try{const d=JSON.parse(r.details_json||'{}');extra=Object.entries(d).map(([k,v])=>`${k}: ${v}`).join(' · ');}catch(_){}
    return `<tr><td>${safe(r.occurred_at)}</td><td>${safe(r.operation)}</td><td>${safe(r.actor)}</td><td>${safe(r.resource_id)}</td><td>${safe(extra)}</td></tr>`;
  }).join('')||'<tr><td colspan="5">No matching audit events.</td></tr>';
}
async function refreshAuditLog(){
  try{auditRows=await api('/api/audit?limit=200');renderAuditRows();}
  catch(error){$('#auditTable').innerHTML=`<tr><td colspan="5">${safe(error.message)}</td></tr>`;}
}
$('#auditRefresh').addEventListener('click',refreshAuditLog);
$('#auditSearch').addEventListener('input',renderAuditRows);
$('#auditType').addEventListener('change',renderAuditRows);


// v0.3.3: read-only, scope-filtered run and trace viewer. No fabricated records.
const durationLabel = x => x===null||x===undefined ? 'Not tracked' : `${Number(x).toLocaleString()} ms`;
// Runtime agent chart colors are defined in static/style.css, not hard-coded here.
// The resolved CSS values drive both ranking swatches and daily stacked bars.
// 20 named series maximum; the rest are grouped as neutral "Others".
const runtimeSeriesColor = (index) => {
  const variable=`--runtime-series-${String(index%20+1).padStart(2,'0')}`;
  return getComputedStyle(document.documentElement).getPropertyValue(variable).trim() || '#087c9f';
};
const runtimeOthersColor = () => getComputedStyle(document.documentElement).getPropertyValue('--runtime-series-others').trim() || '#8497a0';
function renderRuntimePopularity(data){
  if(!$('#runtimeTrend') || !$('#runtimePopularity')) return;
  const ranking=data.ranking||[],days=data.daily||[];
  const rankedTotal=data.runs||0,scopeTotal=data.scope_total_runs||0;
  const others=data.others_runs||0;
  const legend=[...ranking.map((a,i)=>({id:a.agent_id,name:a.name,color:runtimeSeriesColor(i)})),...(others?[{id:'__other__',name:`Others (${data.others_agents})`,color:runtimeOthersColor()}]:[])];
  const palette=new Map(legend.map(x=>[x.id,x.color]));
  const max=Math.max(1,...days.map(d=>d.total));
  const legendHTML=legend.map(x=>`<span class="runtime-legend-item"><i style="background:${x.color}"></i>${safe(x.name)}</span>`).join('');
  $('#runtimeTrend').innerHTML=`<h3>Daily executions by agent (UTC)</h3><p class="provider-helper">${safe(rankedTotal)} recorded runs across ${safe(data.active_agents)} agents${data.search?' matching search':''}; ${safe(scopeTotal)} across selected scope.</p>`+
    (days.length?`<div class="runtime-stacked-bars">${days.map(day=>{
      const segments=legend.map(x=>({name:x.name,color:x.color,runs:x.id==='__other__'?day.others:(day.by_agent[x.id]||0)})).filter(x=>x.runs);
      const bar=segments.map(x=>`<div class="runtime-stack-segment" style="height:${100*x.runs/day.total}%;background:${x.color}" title="${safe(day.date)} · ${safe(x.name)}: ${x.runs} runs"></div>`).join('');
      return `<div class="runtime-stack-day"><strong>${safe(day.total)}</strong><div class="runtime-stack-track" style="height:${Math.max(7,160*day.total/max)}px" title="${safe(day.date)}: ${safe(day.total)} runs">${bar}</div><small>${safe(day.date.slice(5))}</small></div>`;
    }).join('')}</div><div class="runtime-legend">${legendHTML}</div>${data.chart_days_truncated?'<p class="provider-helper">Chart shows the 60 most recent active days; rankings cover the entire selected period.</p>':''}`:'<p class="provider-helper">No recorded executions for this selection.</p>');
  $('#runtimePopularity').innerHTML=`<h3>Most used agents</h3><p class="provider-helper">Run count measures activity, not unique users or business value. Select a row to inspect an agent.</p>`+
    (ranking.length?`<div class="runtime-ranking-list">${ranking.map((a,i)=>`<button type="button" class="runtime-ranking-row" data-popular-agent="${safe(a.agent_id)}"><span class="runtime-rank-number">${i+1}</span><span class="runtime-rank-swatch" style="background:${palette.get(a.agent_id)}"></span><span class="runtime-rank-label" title="${safe(a.name)}">${safe(a.name)}</span><strong>${safe(a.runs)} runs</strong><small>${safe(a.share_pct)}%</small></button>`).join('')}${others?`<div class="runtime-ranking-other"><span class="runtime-rank-swatch" style="background:${runtimeOthersColor()}"></span>Others (${safe(data.others_agents)} agents) <strong>${safe(others)} runs</strong></div>`:''}</div>`:'<p class="provider-helper">No matching agent activity.</p>');
}
async function refreshRuntime(){
  const error=$('#runtimeError');error.textContent='';
  try {
    const selector=$('#runtimeAgentFilter'),saved=selector.value;
    selector.innerHTML='<option value="">All visible agents</option>'+agents.map(a=>`<option value="${safe(a.id)}">${safe(a.name)}</option>`).join('');
    selector.value=agents.some(a=>a.id===saved)?saved:'';
    const id=selector.value,period=$('#runtimePeriod').value;
    const params=new URLSearchParams({period,limit:'100'});
    if(id)params.set('agent_id',id);
    const popularityParams=new URLSearchParams(params);popularityParams.set('top_n',$('#runtimeTopN')?.value||'5');popularityParams.set('search',$('#runtimePopularitySearch')?.value.trim()||'');
    const [summary,records]=await Promise.all([api('/api/runtime/summary?'+params),api('/api/runtime/runs?'+params)]);
    const popularity=await api('/api/runtime/popularity?'+popularityParams).catch(err=>{
      if($('#runtimeTrend')) $('#runtimeTrend').innerHTML='<p class="provider-helper">Popularity chart is unavailable; execution history remains accessible.</p>';
      if($('#runtimePopularity')) $('#runtimePopularity').textContent='Popularity data unavailable.';
      return null;
    });
    const values=[['Runs in period',summary.runs],['Historical runs',summary.historical_runs],['Known outcomes',summary.known_outcomes],['Unknown outcomes',summary.unknown_outcomes],['Success rate',summary.success_rate===null?'Not tracked':`${summary.success_rate}%`],['P95 duration',durationLabel(summary.p95_duration_ms)],['Cost',summary.cost_status]];
    const latest=summary.collections?.[0];
    $('#runtimeCollectionHealth').textContent=latest?`Last successful Azure collection: ${latest.last_success_at} UTC · Window ${latest.window_start} to ${latest.window_end} · ${latest.metadata_rows} rows · ${latest.imported} imported, ${latest.replayed} replayed`:'Collection health: Not tracked — no successful collector heartbeat recorded yet';
    if(popularity) renderRuntimePopularity(popularity);
    $('#runtimeStats').innerHTML=values.map(([label,value])=>`<div class="runtime-stat"><strong>${safe(value)}</strong><small>${safe(label)}</small></div>`).join('');
    const agentNames=new Map(agents.map(a=>[a.id,a.name]));
    $('#runtimeTable').innerHTML=records.map(r=>`<tr><td>${safe(r.started_at)}</td><td>${safe(agentNames.get(r.agent_id)||r.agent_id)}</td><td>${safe(r.source)}</td><td>${safe(r.status)}</td><td>${safe(durationLabel(r.duration_ms))}</td><td><code>${safe(r.trace_id||'Not tracked')}</code></td><td><button type="button" class="secondary-btn" data-runtime-id="${safe(r.id)}">View spans</button></td></tr>`).join('')||'<tr><td colspan="7">No actual execution telemetry recorded for the selected scope.</td></tr>';
  } catch(ex){error.textContent=ex.message;}
}
$('#runtimeRefresh').addEventListener('click',refreshRuntime);
$('#runtimeAgentFilter').addEventListener('change',()=>{$('#runtimeTrace').textContent='No run selected.';refreshRuntime();});
$('#runtimePeriod').addEventListener('change',()=>{$('#runtimeTrace').textContent='No run selected.';refreshRuntime();});
$('#runtimeTopN')?.addEventListener('change',refreshRuntime);
let popularitySearchTimer;$('#runtimePopularitySearch')?.addEventListener('input',()=>{clearTimeout(popularitySearchTimer);popularitySearchTimer=setTimeout(refreshRuntime,250);});
$('#runtimePopularity')?.addEventListener('click',e=>{const button=e.target.closest('[data-popular-agent]');if(!button)return;$('#runtimeAgentFilter').value=button.dataset.popularAgent;$('#runtimePopularitySearch').value='';refreshRuntime();});
$('#runtimeTable').addEventListener('click',async e=>{
  const btn=e.target.closest('[data-runtime-id]');if(!btn)return;
  const output=$('#runtimeTrace');output.textContent='Loading trace…';
  try {
    const r=await api(`/api/runtime/runs/${encodeURIComponent(btn.dataset.runtimeId)}`);
    output.innerHTML=`<p><strong>Run:</strong> ${safe(r.external_run_id)} · <strong>Trace:</strong> <code>${safe(r.trace_id||'Not tracked')}</code> · <strong>Status:</strong> ${safe(r.status)}</p>`+
      (r.spans.length?`<div class="table-wrap"><table><thead><tr><th>SPAN</th><th>TYPE</th><th>OPERATION</th><th>STATUS</th><th>DURATION</th><th>PARENT</th></tr></thead><tbody>${r.spans.map(s=>`<tr><td><code>${safe(s.span_id)}</code></td><td>${safe(s.kind)}</td><td>${safe(s.name)}</td><td>${safe(s.status)}</td><td>${safe(durationLabel(s.duration_ms))}</td><td><code>${safe(s.parent_span_id||'Root')}</code></td></tr>`).join('')}</tbody></table></div>`:'<p>No spans were included in this run.</p>');
  }catch(ex){output.textContent=ex.message;}
});

// Azure resource-scope ActualCost visualization. Summarize the FULL returned set;
// show friendly resource labels, preserving exact scope/resource/day evidence in details.
let azureCostRows = [];
const azureCostMoney = (amount, currency) => {
  const value = Number(amount);
  if(!Number.isFinite(value)) return 'Not tracked';
  try { return new Intl.NumberFormat('en-US',{style:'currency',currency,minimumFractionDigits:2,maximumFractionDigits:4}).format(value); }
  catch { return `${value.toFixed(4)} ${currency}`; }
};
const azureService = id => {
  const x=String(id||'');
  const m=x.match(/\/providers\/microsoft\.([^/]+)\//i);
  if(m){const key=m[1].toLowerCase();return ({cognitiveservices:'Azure AI / Foundry',operationalinsights:'Log Analytics',insights:'Application Insights',storage:'Storage',web:'App Service / Functions',monitor:'Azure Monitor',containerregistry:'Container Registry',keyvault:'Key Vault',machinelearningservices:'Azure ML'}[key] || `Microsoft.${m[1]}`);}
  return x?'Other / unclassified Azure cost':'Unassigned charges';
};
const azureResourceName = id => {
  if(!id)return 'Unassigned charge';
  const parts=String(id).split('/').filter(Boolean);
  if(!parts.length)return 'Unassigned charge';
  const last=parts.at(-1);
  return last.length>75?last.slice(0,72)+'…':last;
};
function renderAzureCosts(){
  const rows=azureCostRows;
  const currencies=new Map(), services=new Map(), resources=new Map();
  for(const row of rows){
    const amount=Number(row.amount);
    if(!Number.isFinite(amount))continue;
    const currency=row.currency||'UNKNOWN';
    currencies.set(currency,(currencies.get(currency)||0)+amount);
    const service=azureService(row.resource_id);
    const svcKey=currency+'\u0000'+service;
    services.set(svcKey,(services.get(svcKey)||0)+amount);
    const key=currency+'\u0000'+String(row.resource_id||'').toLowerCase()+'\u0000'+String(row.scope||'').toLowerCase();
    if(!resources.has(key)) resources.set(key,{id:row.resource_id||'',scope:row.scope,currency,service,total:0,days:new Set(),records:0});
    const item=resources.get(key);item.total+=amount;item.records++;item.days.add(row.usage_day);
  }
  const totals=[...currencies].sort((a,b)=>a[0].localeCompare(b[0]));
  $('#finopsAzureKpis').innerHTML=totals.length?
    totals.map(([currency,total])=>`<div class="finops-cost-kpi"><strong>${safe(azureCostMoney(total,currency))}</strong><small>Total Azure ActualCost · ${safe(currency)}</small></div>`).join('')+
    `<div class="finops-cost-kpi"><strong>${safe(resources.size)}</strong><small>Resource groups in report</small></div><div class="finops-cost-kpi"><strong>${safe(rows.length)}</strong><small>Daily charge records</small></div>`:
    '<div class="finops-cost-kpi"><strong>Not tracked</strong><small>No Azure scope costs imported</small></div>';
  const orderedServices=[...services].map(([key,total])=>{const [currency,service]=key.split('\u0000');return {currency,service,total};}).sort((a,b)=>a.currency.localeCompare(b.currency)||b.total-a.total);
  const maxByCurrency=new Map();for(const s of orderedServices)maxByCurrency.set(s.currency,Math.max(maxByCurrency.get(s.currency)||0,Math.abs(s.total)));
  $('#finopsServiceBars').innerHTML=orderedServices.length?orderedServices.map((s,i)=>{
    const pct=maxByCurrency.get(s.currency)?Math.min(100,Math.abs(s.total)/maxByCurrency.get(s.currency)*100):0;
    return `<div class="finops-service-row"><div class="finops-service-heading"><span title="${safe(s.service)}">${safe(s.service)}</span><strong>${safe(azureCostMoney(s.total,s.currency))}</strong></div><div class="finops-service-track"><div class="finops-service-fill" style="width:${pct.toFixed(2)}%;background:var(--runtime-series-0${i%6+1},var(--brand-blue))"></div></div></div>`;
  }).join(''):'<p class="provider-helper">No cost records for this period.</p>';
  const q=($('#finopsResourceSearch')?.value||'').trim().toLowerCase();
  const entries=[...resources.values()].filter(r=>!q||[r.id,r.scope,r.service,azureResourceName(r.id)].some(v=>String(v||'').toLowerCase().includes(q)))
    .sort((a,b)=>a.currency.localeCompare(b.currency)||b.total-a.total);
  $('#finopsAzureCosts').innerHTML=entries.slice(0,100).map(r=>{
    const id=r.id||'(unassigned)';
    const days=[...r.days].sort();const period=days.length===1?days[0]:`${days[0]} to ${days.at(-1)}`;
    return `<tr><td><strong class="finops-resource-name" title="${safe(id)}">${safe(azureResourceName(r.id))}</strong><small>${safe(r.service)}</small></td><td class="finops-charge">${safe(azureCostMoney(r.total,r.currency))}</td><td><details class="finops-charge-detail"><summary>View</summary><div><b>Azure resource ID</b><code>${safe(id)}</code><b>Azure scope</b><code>${safe(r.scope)}</code><b>Charge dates</b><span>${safe(period)} · ${r.records} daily record(s)</span><b>Classification</b><span>Azure scope ActualCost · not agent-attributed · not invoice-final</span></div></details></td></tr>`;
  }).join('')||'<tr><td colspan="3">No matching Azure resource costs.</td></tr>';
  $('#finopsResourceCount').textContent=entries.length>100?`Showing 100 of ${entries.length} resources. Refine the search to see more.`:`${entries.length} resource(s) in the selected period.`;
}
$('#finopsResourceSearch')?.addEventListener('input',renderAzureCosts);

// v0.3.4.0: truthful partial coverage. No guessed prices or zero-filled unknowns.
async function refreshFinops(){
  const error=$('#finopsError');if(!error)return;
  error.textContent='';
  try {
    const result=await api('/api/finops/summary?period='+encodeURIComponent($('#finopsPeriod').value));
    const canEstimates=(currentIdentity?.capabilities||[]).includes('finops.estimates.view');
    const values=[['Observed model operations',result.usage_operations],
      ['Input tokens (observed)',result.input_token_samples?result.input_tokens_observed.toLocaleString():'Not tracked'],
      ['Output tokens (observed)',result.output_token_samples?result.output_tokens_observed.toLocaleString():'Not tracked'],
      ['Estimated cost (covered only)',!canEstimates||result.estimated_usd===null?'Not tracked':money(Number(result.estimated_usd))],
      ['Operations with estimates',canEstimates?`${result.estimated_operations}/${result.usage_operations}`:'Restricted'],
      ['Verified billed charges',result.billed_status]];
    $('#finopsStats').innerHTML=values.map(([label,value])=>`<div class="runtime-stat"><strong>${safe(value)}</strong><small>${safe(label)}</small></div>`).join('');
    $('#finopsNotice').textContent=`${result.notice} Cost estimate coverage: ${result.estimation_status}. Azure scope ActualCost is separately reported; final invoices are not reconciled.`;
    // Enterprise Azure billing is restricted to Admin/Auditor.
    if((currentIdentity?.capabilities||[]).includes('finops.billing.view')){
    const costs=await api('/api/finops/azure-costs?period='+encodeURIComponent($('#finopsPeriod').value));
    $('#finopsAzureCostStatus').textContent=costs.records
      ? `${costs.records} Azure resource/day charge records · Last collected: ${costs.last_collection || 'Not tracked'} · Not agent-attributed or final invoice charges.`
      : 'Not tracked — no Azure Cost Management ActualCost records imported.';
    azureCostRows=costs.rows||[];
    renderAzureCosts();
    }
    $('#finopsTable').innerHTML=(result.by_agent||[]).map(a=>`<tr><td>${safe(a.name)}</td><td>${safe(a.operations)}</td><td>${a.input_samples?safe(a.input_tokens_observed.toLocaleString()):'Not tracked'} (${safe(a.input_samples)} observed)</td><td>${a.output_samples?safe(a.output_tokens_observed.toLocaleString()):'Not tracked'} (${safe(a.output_samples)} observed)</td><td>${!canEstimates||a.estimated_usd===null?'Not tracked':money(Number(a.estimated_usd))} (${safe(a.estimated_operations)}/${safe(a.operations)} covered)</td><td>${!canEstimates?'Restricted':a.approved_monthly_budget_usd===null?'Not approved':money(a.approved_monthly_budget_usd)}<small>${safe(a.budget_comparison)}</small></td></tr>`).join('') || '<tr><td colspan="6">No observed model token telemetry imported. Runtime runs may still exist.</td></tr>';
  }catch(e){error.textContent=e.message;}
}
$('#finopsRefresh')?.addEventListener('click',refreshFinops);
$('#finopsPeriod')?.addEventListener('change',refreshFinops);


// v0.3.5 Trust Graph UI: read-only, server-scoped and evidence-based.
let trustGraphData={tools:[],links:[]}, trustAgents=[], trustConnections=[];
let trustTab='graph', trustSelectedNode=null;
let trustViewport={width:840,height:310,scale:1,fitScale:1};
let providerInventoryData=[];
const trustClamp=(n,min,max)=>Math.max(min,Math.min(max,n));
function trustFitScale(){
  const canvas=$('#trustGraphCanvas');
  return trustClamp(Math.min((canvas.clientWidth-16)/trustViewport.width,(canvas.clientHeight-16)/trustViewport.height),0.05,2);
}
function trustApplyZoom(scale){
  const svg=$('#trustGraphCanvas svg');
  if(!svg)return;
  trustViewport.scale=trustClamp(scale,0.05,4);
  svg.style.width=`${Math.round(trustViewport.width*trustViewport.scale)}px`;
  svg.style.height=`${Math.round(trustViewport.height*trustViewport.scale)}px`;
  svg.style.minHeight='0';
  $('#trustZoomLevel').textContent=`${Math.round(trustViewport.scale*100)}%`;
  $('#trustZoomIn').disabled=trustViewport.scale>=3.99;
  $('#trustZoomOut').disabled=trustViewport.scale<=0.051;
}
function trustFitView(){
  trustViewport.fitScale=trustFitScale();
  trustApplyZoom(trustViewport.fitScale);
  $('#trustGraphCanvas').scrollTo({top:0,left:0});
}

const trustDate = value => value ? shortDate(value) : 'Not tracked';
const trustKind = type => type==='observed_invocation' ? 'Reported invocation' : 'Configured relationship';
const trustAgentLabel = id => trustAgents.find(a=>a.id===id)?.name || id;
const trustConnectionLabel = id => trustConnections.find(c=>c.id===id)?.label || id;
const trustFilter = () => {
  const q=$('#trustSearch').value.trim().toLowerCase();
  const evidence=$('#trustEvidenceFilter').value;
  const matching=trustGraphData.links.filter(l=>!evidence||l.evidence_type===evidence);
  const match=(...fields)=>!q||fields.some(v=>String(v||'').toLowerCase().includes(q));
  const toolIds=new Set(trustGraphData.tools.filter(t=>match(t.name,t.external_id,t.namespace,t.capability,trustConnectionLabel(t.connection_id))).map(t=>t.id));
  const linkIds=new Set(matching.filter(l=>{
    const t=trustGraphData.tools.find(x=>x.id===l.tool_id);
    return match(trustAgentLabel(l.agent_id),l.agent_id,t?.name,t?.namespace,l.evidence_type,l.evidence_reference)||(!q && toolIds.has(l.tool_id));
  }).map(l=>l.id));
  const links=matching.filter(l=>linkIds.has(l.id));
  const linkedTools=new Set(links.map(l=>l.tool_id));
  const tools=trustGraphData.tools.filter(t=>toolIds.has(t.id)||linkedTools.has(t.id));
  return {tools,links};
};
function renderTrustGraph(){
  const {tools,links}=trustFilter();
  const q=$('#trustSearch').value.trim().toLowerCase();
  const evidence=$('#trustEvidenceFilter').value;
  const ids=new Set(links.map(l=>l.agent_id));
  const toolIds=new Set(links.map(l=>l.tool_id));
  // Including registered agents without verified links is meaningful but keeps the visualization bounded.
  const graphAgents=trustAgents.filter(a=>ids.has(a.id)||(!q&&!evidence));
  const graphTools=tools.filter(t=>toolIds.has(t.id)||(!q&&!evidence));
  const rows=[...graphAgents.map(a=>({id:a.id,label:a.name||a.id,kind:'agent'})),...graphTools.map(t=>({id:t.id,label:t.name,kind:'tool'}))];
  // Prefer connected nodes in large estates, preserving a slot for each side.
  const orderedAgents=graphAgents.slice().sort((a,b)=>Number(ids.has(b.id))-Number(ids.has(a.id)));
  const orderedTools=graphTools.slice().sort((a,b)=>Number(toolIds.has(b.id))-Number(toolIds.has(a.id)));
  const agentCap=orderedTools.length?30:60, toolCap=orderedAgents.length?30:60;
  const visible=[...orderedAgents.slice(0,agentCap).map(a=>({id:a.id,label:a.name||a.id,kind:'agent'})),...orderedTools.slice(0,toolCap).map(t=>({id:t.id,label:t.name,kind:'tool'}))];
  const visibleIds=new Set(visible.map(r=>r.id));
  const visibleLinks=links.filter(l=>visibleIds.has(l.agent_id)&&visibleIds.has(l.tool_id));
  const counts=new Map();links.forEach(l=>{counts.set(l.tool_id,(counts.get(l.tool_id)||0)+1);});
  $('#trustStats').innerHTML=[['Discovered tools',trustGraphData.tools.length],['Reported relationships',trustGraphData.links.length],['Configured relationships',trustGraphData.links.filter(l=>l.evidence_type==='declared_configuration').length],['Reported invocations',trustGraphData.links.filter(l=>l.evidence_type==='observed_invocation').length]].map(([label,v])=>`<div class="runtime-stat"><strong>${safe(v)}</strong><small>${safe(label)}</small></div>`).join('');
  $('#trustInventoryRows').innerHTML=tools.map(t=>`<tr><td><strong>${safe(t.name)}</strong><small>${safe(t.description||t.external_id)}</small></td><td>${safe(trustConnectionLabel(t.connection_id))}<small>${safe(t.namespace)}</small></td><td>${safe(t.capability)}</td><td>${safe(counts.get(t.id)||0)}</td><td>${safe(trustDate(t.last_seen))}</td></tr>`).join('')||'<tr><td colspan="5">No matching tools. Provider MCP discovery is not connected yet.</td></tr>';
  $('#trustEvidenceRows').innerHTML=links.map(l=>{const t=trustGraphData.tools.find(t=>t.id===l.tool_id);return `<tr><td>${safe(trustAgentLabel(l.agent_id))}</td><td>${safe(t?.name||l.tool_id)}</td><td>${safe(trustKind(l.evidence_type))}</td><td class="trust-evidence-ref" title="${safe(l.evidence_reference)}">${safe(l.evidence_reference)}</td><td>${safe(trustDate(l.last_seen))}</td></tr>`;}).join('')||'<tr><td colspan="5">No evidence-backed agent-to-tool relationships recorded.</td></tr>';
  const canvas=$('#trustGraphCanvas');
  if(!rows.length){ canvas.innerHTML='<div class="trust-empty"><strong>No Trust Graph relationships yet</strong><p>Connect GitHub or Atlassian after native MCP discovery is available, or ingest an authorized tool snapshot. No agents or tool calls are simulated.</p></div>';$('#trustGraphLimit').textContent='';$('#trustSelectedDetail').textContent='No graph node selected.';$('#trustZoomLevel').textContent='—';return;}
  // Display a deterministic, bounded two-column graph; the tables retain every matching record.
  const left=visible.filter(v=>v.kind==='agent'),right=visible.filter(v=>v.kind==='tool');
  const h=Math.max(310,Math.max(left.length,right.length)*72+50);const w=840;
  const pos=new Map();
  const node=(v,i,total,x)=>{const y=45+(i+0.5)*Math.max(62,(h-90)/Math.max(1,total));pos.set(v.id,{x,y});const color=v.kind==='agent'?'#e4f4fa':'#fff2df';const stroke=v.kind==='agent'?'#1683a1':'#d08d34';const label=v.label.length>25?v.label.slice(0,24)+'…':v.label;return `<g class="trust-node" data-trust-node="${safe(v.id)}" role="button" tabindex="0" aria-label="Inspect ${safe(v.kind)} ${safe(v.label)}"><rect x="${x-102}" y="${y-24}" rx="8" width="204" height="48" fill="${color}" stroke="${stroke}" stroke-width="1.5"/><text x="${x}" y="${y+4}" font-size="12" text-anchor="middle" fill="#19475b">${safe(label)}</text></g>`;};
  const nodes=[...left.map((v,i)=>node(v,i,left.length,150)),...right.map((v,i)=>node(v,i,right.length,690))];
  const lines=visibleLinks.map(l=>{const a=pos.get(l.agent_id),t=pos.get(l.tool_id);if(!a||!t)return '';const observed=l.evidence_type==='observed_invocation';return `<path d="M ${a.x+102} ${a.y} C 410 ${a.y}, 430 ${t.y}, ${t.x-102} ${t.y}" fill="none" stroke="${observed?'#16876c':'#a9b2c1'}" stroke-width="${observed?3:2}" ${observed?'':'stroke-dasharray="6 5"'}/>`;}).join('');
  canvas.innerHTML=`<svg class="trust-svg" viewBox="0 0 ${w} ${h}" width="100%" style="min-height:240px" role="img" aria-label="${left.length} agents, ${right.length} tools and ${visibleLinks.length} visible relationships">${lines}${nodes.join('')}</svg>`;
  trustViewport.width=w;trustViewport.height=h;trustFitView();
  $('#trustGraphLimit').textContent=rows.length>visible.length?`Showing ${visible.length} of ${rows.length} nodes. Search to narrow the graph; Inventory and Evidence retain all matching records.`:`${visible.length} nodes · ${visibleLinks.length} evidence relationships shown. Select a node to inspect.`;
  if(trustSelectedNode) showTrustNode(trustSelectedNode); else $('#trustSelectedDetail').textContent='Select a graph node to inspect its relationships.';
}
function showTrustNode(id){
  trustSelectedNode=id;
  const t=trustGraphData.tools.find(t=>t.id===id),a=trustAgents.find(a=>a.id===id);
  const related=trustGraphData.links.filter(l=>l.tool_id===id||l.agent_id===id);
  const detail=$('#trustSelectedDetail');
  if(!t&&!a){detail.textContent='Select a graph node to inspect.';return;}
  const name=t?.name||a?.name||id;
  detail.innerHTML=`<strong>${safe(name)}</strong><p>${t?`Tool · ${safe(trustConnectionLabel(t.connection_id))} · ${safe(t.namespace)}`:`Agent · ${safe(a?.provider||'Unspecified provider')}`}</p><p>${related.length} evidence relationship(s) recorded.</p>`+(related.length?`<ul>${related.slice(0,20).map(l=>`<li>${safe(trustKind(l.evidence_type))} · ${safe(t?trustAgentLabel(l.agent_id):trustGraphData.tools.find(x=>x.id===l.tool_id)?.name||l.tool_id)} · ${safe(l.evidence_reference)}</li>`).join('')}</ul>`:'<p>No agent-to-tool relationship evidence recorded.</p>');
}
async function refreshTrustGraph(){
  const status=$('#trustStatus');status.textContent='Loading authorized graph data…';
  try{
    const [graph,visibleAgents,visibleConnections]=await Promise.all([api('/api/trust-graph'),api('/api/agents'),api('/api/connections').catch(()=>[])]);
    trustGraphData={tools:graph.tools||[],links:graph.links||[]};trustAgents=visibleAgents||[];trustConnections=visibleConnections||[];
    status.textContent='Read-only snapshot. GitHub resources are in the Provider Inventory below; Atlassian advertised MCP tools appear in tool inventory. No agent-to-tool access is inferred; reported invocation evidence requires source verification.';
    await refreshProviderInventory();
    renderTrustGraph();
  }catch(err){trustGraphData={tools:[],links:[]};trustAgents=[];trustConnections=[];status.textContent=`Unable to load Trust Graph: ${err.message}`;$('#trustGraphCanvas').textContent='Trust Graph unavailable.';$('#trustInventoryRows').innerHTML='';$('#trustEvidenceRows').innerHTML='';$('#trustStats').innerHTML='';}
}
function selectTrustTab(tab){trustTab=tab;document.querySelectorAll('[data-trust-tab]').forEach(b=>{const active=b.dataset.trustTab===tab;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));});['graph','inventory','evidence'].forEach(t=>{$(`#trust${t[0].toUpperCase()+t.slice(1)}Tab`).hidden=t!==tab;});if(tab==='graph' && $('#trustGraphCanvas svg'))trustFitView();}
$('#trustRefresh').addEventListener('click',refreshTrustGraph);
$('#trustSearch').addEventListener('input',renderTrustGraph);
$('#trustEvidenceFilter').addEventListener('change',renderTrustGraph);
$('#trustZoomIn').addEventListener('click',()=>trustApplyZoom(trustViewport.scale*1.25));
$('#trustZoomOut').addEventListener('click',()=>trustApplyZoom(trustViewport.scale/1.25));
$('#trustZoomFit').addEventListener('click',trustFitView);
window.addEventListener('resize',()=>{if(trustTab==='graph' && !$('#trustGraphView').hidden && $('#trustGraphCanvas svg')) trustFitView();});
document.querySelectorAll('[data-trust-tab]').forEach(b=>b.addEventListener('click',()=>selectTrustTab(b.dataset.trustTab)));
$('#trustGraphCanvas').addEventListener('click',e=>{const n=e.target.closest('[data-trust-node]');if(n)showTrustNode(n.dataset.trustNode);});
$('#trustGraphCanvas').addEventListener('keydown',e=>{const n=e.target.closest('[data-trust-node]');if(n&&(e.key==='Enter'||e.key===' ')){e.preventDefault();showTrustNode(n.dataset.trustNode);}});

function providerInventoryKind(provider){
  if(provider==='github_inventory')return 'GitHub';
  if(provider==='atlassian_rovo_mcp')return 'Atlassian';
  return provider||'Other provider';
}
function providerInventoryConnection(id){return trustConnections.find(c=>String(c.id)===String(id));}
function renderProviderInventory(){
 const root=$('#providerInventoryRows');if(!root)return;
 const provider=$('#providerInventoryFilter').value;
 const query=$('#providerInventorySearch').value.trim().toLowerCase();
 const rows=providerInventoryData.filter(r=>{
   const conn=providerInventoryConnection(r.connection_id);
   const key=conn?.provider||'unknown';
   return (!provider||key===provider)&&(!query||[r.name,r.kind,conn?.label,key].some(x=>String(x||'').toLowerCase().includes(query)));
 });
 root.innerHTML=rows.length?rows.map(x=>`<tr><td>${safe(x.kind)}</td><td>${safe(x.name)}</td><td>${safe(trustConnectionLabel(x.connection_id))}</td><td>${safe(trustDate(x.last_seen))}</td></tr>`).join(''):'<tr><td colspan="4">No resources match the selected provider or search.</td></tr>';
 $('#providerInventoryCount').textContent=`Showing ${rows.length} of ${providerInventoryData.length} resources`;
}
async function refreshProviderInventory(){
 const root=$('#providerInventoryRows');if(!root)return;
 try{
  providerInventoryData=await api('/api/provider-inventory');
  const selector=$('#providerInventoryFilter');const selected=selector.value;
  const keys=[...new Set(providerInventoryData.map(r=>providerInventoryConnection(r.connection_id)?.provider||'unknown'))].sort();
  selector.innerHTML='<option value="">All providers</option>'+keys.map(k=>`<option value="${safe(k)}">${safe(providerInventoryKind(k))}</option>`).join('');
  if(keys.includes(selected)) selector.value=selected;
  renderProviderInventory();
 }catch(err){providerInventoryData=[];root.innerHTML=`<tr><td colspan="4">Inventory unavailable: ${safe(err.message)}</td></tr>`;$('#providerInventoryCount').textContent='';}
}
$('#providerInventoryFilter').addEventListener('change',renderProviderInventory);
$('#providerInventorySearch').addEventListener('input',renderProviderInventory);
