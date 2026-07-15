import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, type ActionResult, type ActionSpec, type Citation, type Integration, type Principal } from "./api";
import { Actions } from "./tabs/Actions";
import { Agents } from "./tabs/Agents";
import { Learning } from "./tabs/Learning";

type View = "command" | "documents" | "actions" | "agents" | "learning" | "audit" | "integrations";
type ChatMessage = { role: "assistant" | "user"; text: string; citations?: Citation[]; route?: string; actionResult?: ActionResult | null };

// Default to the platform-prebuilt principal (FDA/OSHA/FTC + open-dataset summaries):
// it is the identity this pilot deployment's retail_core_open_v1 load job provisions,
// so it authenticates out of the box on the running instance. It still requires that
// one-off pack/fixture load to have been run — see RENDER.md — it is not created
// automatically on a brand new database. Tenant fixture projects (Australia Region /
// Global Region under tenant "retail") also work once loaded, but their project ids
// are generated per-deployment; paste one into Project ID below instead.
const INITIAL_PRINCIPAL: Principal = { userId: "u_platform", tenantId: "platform", projectId: "prj_prebuilt_retail_core" };
// Browsers that signed in before the defaults above were fixed still have the old,
// never-valid identity cached in localStorage (see git history: it used to default to
// tenant "northstar" / user "u_ops_manager"). Without this migration those sessions would
// keep replaying a principal that 403s forever, even after the app itself is redeployed.
const STALE_PRINCIPALS: Partial<Principal>[] = [{ userId: "u_ops_manager", tenantId: "northstar" }];
const DEFAULTS_MIGRATION_KEY = "retailops.defaultsMigration";
const DEFAULTS_MIGRATION_VERSION = "2024-07-platform-default";

function loadStoredPrincipal(): Principal {
  let stored: Principal | null = null;
  try { stored = JSON.parse(localStorage.getItem("retailops.principal") || "null"); } catch { stored = null; }
  if (!stored || !stored.userId || !stored.tenantId || !stored.projectId) return INITIAL_PRINCIPAL;
  const alreadyMigrated = localStorage.getItem(DEFAULTS_MIGRATION_KEY) === DEFAULTS_MIGRATION_VERSION;
  const isKnownStale = STALE_PRINCIPALS.some(s => s.userId === stored!.userId && s.tenantId === stored!.tenantId);
  if (isKnownStale && !alreadyMigrated) return INITIAL_PRINCIPAL;
  return stored;
}
const Icon = ({ children }: { children: ReactNode }) => <span className="icon" aria-hidden>{children}</span>;

function download(filename: string, type: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function Donut({ value = 76 }: { value?: number }) {
  const offset = 100 - value;
  return <div className="donut"><svg viewBox="0 0 42 42"><circle className="track" cx="21" cy="21" r="16"/><circle className="fill" cx="21" cy="21" r="16" pathLength="100" strokeDasharray="100" strokeDashoffset={offset}/></svg><strong>{value}%</strong></div>;
}

function MiniBars() {
  return <div className="mini-bars" aria-label="Weekly action activity">{[38,56,44,78,62,92,71,84].map((h,i)=><span key={i} style={{height:`${h}%`}} className={i===5?"hot":""}/>)}</div>;
}

export function App() {
  const [principal, setPrincipal] = useState<Principal>(loadStoredPrincipal);
  const [signedIn, setSignedIn] = useState(() => Boolean(localStorage.getItem("retailops.signedIn")));
  useEffect(() => {
    localStorage.setItem(DEFAULTS_MIGRATION_KEY, DEFAULTS_MIGRATION_VERSION);
    localStorage.setItem("retailops.principal", JSON.stringify(principal));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [view, setView] = useState<View>("command");
  const [leftOpen, setLeftOpen] = useState(true); const [rightOpen, setRightOpen] = useState(true);
  const [settings, setSettings] = useState(false); const [profileOpen, setProfileOpen] = useState(false);
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof api.overview>> | null>(null);
  const [docs, setDocs] = useState<Awaited<ReturnType<typeof api.documents>>["documents"]>([]);
  const [actions, setActions] = useState<ActionSpec[]>([]);
  const [runs, setRuns] = useState<Awaited<ReturnType<typeof api.audit>>["runs"]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [integrationBusy, setIntegrationBusy] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([{role:"assistant",text:"Good morning. I’m ready to turn your project records into grounded answers and auditable outcomes. What do you need to know?"}]);
  const [question, setQuestion] = useState(""); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false); const [filename, setFilename] = useState("operations-note.txt"); const [fileText, setFileText] = useState("");
  const [actionResult, setActionResult] = useState<ActionResult | null>(null);
  const [docSearch, setDocSearch] = useState("");

  const ready = Boolean(principal.userId && principal.tenantId && principal.projectId);
  const refresh = useCallback(async () => {
    if (!ready) return;
    const results = await Promise.allSettled([api.overview(principal), api.documents(principal), api.actions(principal), api.audit(principal), api.integrations(principal)]);
    if (results[0].status === "fulfilled") setOverview(results[0].value);
    if (results[1].status === "fulfilled") setDocs(results[1].value.documents);
    if (results[2].status === "fulfilled") setActions(results[2].value.actions);
    if (results[3].status === "fulfilled") setRuns(results[3].value.runs);
    if (results[4].status === "fulfilled") setIntegrations(results[4].value.integrations);
    const failed = results.find(r=>r.status==="rejected"); if (failed) setNotice(String((failed as PromiseRejectedResult).reason));
  }, [principal, ready]);
  useEffect(()=>{ refresh(); },[refresh]);

  const signIn = () => { if (!ready) { setNotice("Enter your project ID to open the secure workspace."); return; } localStorage.setItem("retailops.principal",JSON.stringify(principal)); localStorage.setItem("retailops.signedIn","1"); setSignedIn(true); };
  const ask = async (override?: string) => {
    const q=(override ?? question).trim(); if(!q||busy) return; setMessages(m=>[...m,{role:"user",text:q}]); setQuestion(""); setBusy(true); setNotice("");
    try { const res=await api.ask(principal,q); setMessages(m=>[...m,{role:"assistant",text:res.answer,citations:res.citations,route:res.route,actionResult:res.action_result??null}]); if(res.action_result) setActionResult(res.action_result); }
    catch(e){setMessages(m=>[...m,{role:"assistant",text:"I couldn’t complete that request. "+String(e)}]);} finally{setBusy(false); refresh();}
  };
  const ingest = async () => { if(!fileText.trim()) return; setBusy(true); try{await api.ingest(principal,filename,fileText,"project_record");setFileText("");setUploadOpen(false);setNotice("Document indexed successfully.");await refresh();}catch(e){setNotice(String(e));}finally{setBusy(false);} };
  const testIntegration = async (connectorId: string) => { setIntegrationBusy(connectorId); setNotice(""); try{const r=await api.testIntegration(principal,connectorId);setNotice(String((r as {message?: string}).message ?? `${connectorId}: test complete.`));await refresh();}catch(e){setNotice(String(e));}finally{setIntegrationBusy("");} };
  const syncIntegration = async (connectorId: string) => { setIntegrationBusy(connectorId); setNotice(""); try{const r=await api.syncIntegration(principal,connectorId);const ok=(r as {ok?: boolean}).ok;const count=(r as {record_count?: number}).record_count;setNotice(ok?`${connectorId}: synced ${count ?? 0} record(s).`:String((r as {message?: string}).message ?? `${connectorId}: sync failed.`));await refresh();}catch(e){setNotice(String(e));}finally{setIntegrationBusy("");} };
  const exportPowerBi = async (kind: "export_csv" | "export_xlsx") => { setIntegrationBusy("power_bi"); setNotice(""); try{const r=await api.syncIntegration(principal,"power_bi",{operation:kind});const result=(r as {result?: {content_base64?: string; content_type?: string; filename?: string}}).result; if(result?.content_base64){const bytes=atob(result.content_base64);const arr=new Uint8Array(bytes.length);for(let i=0;i<bytes.length;i++)arr[i]=bytes.charCodeAt(i);const blob=new Blob([arr],{type:result.content_type||"application/octet-stream"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=result.filename||"retailops-export";a.click();URL.revokeObjectURL(url);setNotice(`Power BI: downloaded ${result.filename}.`);}}catch(e){setNotice(String(e));}finally{setIntegrationBusy("");} };
  const exportOutcome=(kind:"pdf"|"doc"|"xls")=>{
    const rows=runs.map(r=>`<tr><td>${r.action_id}</td><td>${r.status}</td><td>${new Date(r.started_at).toLocaleString()}</td><td>${r.evidence_count}</td></tr>`).join("");
    const outBlock = actionResult ? `<h2>Latest deliverable: ${actionResult.action_id}</h2><pre>${JSON.stringify(actionResult.output ?? {}, null, 2).replace(/</g,"&lt;")}</pre>` : "";
    const html=`<html><body><h1>RetailOps Outcome Report</h1><p>Project: ${principal.projectId}</p><p>Documents: ${overview?.document_count??0}</p><table border="1"><tr><th>Outcome</th><th>Status</th><th>Date</th><th>Evidence</th></tr>${rows}</table>${outBlock}</body></html>`;
    const ext = kind==="pdf"?"html":kind==="doc"?"doc":"xls";
    const mime = kind==="pdf"?"text/html":kind==="doc"?"application/msword":"application/vnd.ms-excel";
    download(`retailops-${principal.projectId}.${ext}`, mime, html);
  };

  if(!signedIn) return <div className="login-page"><div className="edge-word left">PILOT</div><div className="edge-word right">SDKSYSTEMS</div><section className="login-card"><div className="mark">N</div><p className="eyebrow">NORTHSTAR INTELLIGENCE</p><h1>Retail operations,<br/><em>made decisive.</em></h1><p className="login-copy">Secure, grounded intelligence for every store, project and operational decision.</p><div className="login-grid"><label>User ID<input value={principal.userId} onChange={e=>setPrincipal({...principal,userId:e.target.value})}/></label><label>Tenant<input value={principal.tenantId} onChange={e=>setPrincipal({...principal,tenantId:e.target.value})}/></label></div><label>Project ID<input autoFocus value={principal.projectId} onChange={e=>setPrincipal({...principal,projectId:e.target.value})} placeholder="e.g. prj_prebuilt_retail_core" onKeyDown={e=>e.key==="Enter"&&signIn()}/></label><p className="login-hint">Prefilled with the platform-prebuilt pilot identity (loaded on this deployment). To open a tenant project instead, ask an admin for its User ID / Tenant / Project ID — every request is authorised server-side against that exact triple.</p>{notice&&<p className="form-error">{notice}</p>}<button className="signin" onClick={signIn}>Enter workspace <span>→</span></button><footer><span>● Systems operational</span><span>Protected workspace</span></footer></section></div>;

  const activeOutcomes = runs.filter(r=>r.status==="success").length;
  const filteredDocs = docs.filter(d=>d.filename.toLowerCase().includes(docSearch.trim().toLowerCase()));
  return <div className={`shell ${!leftOpen?"left-closed":""} ${!rightOpen?"right-closed":""}`}>
    <aside className="rail"><div className="rail-logo">N</div><button className="rail-btn" onClick={()=>setLeftOpen(v=>!v)} title="Toggle navigator">⌘</button><div className="rail-spacer"/><button className="rail-btn" onClick={()=>setSettings(true)}>⚙</button></aside>
    <aside className="left-panel">
      <div className="panel-head"><div><span className="eyebrow">WORKSPACE</span><strong>Northstar Retail</strong></div><button className="ghost" onClick={()=>setLeftOpen(false)}>‹</button></div>
      <button className={`nav-item ${view==="command"?"active":""}`} onClick={()=>setView("command")}><Icon>⌁</Icon> Command center <small>{activeOutcomes}</small></button>
      <p className="nav-label">PROJECT</p><div className="project-card"><span className="project-icon">NR</span><div><strong>{principal.projectId}</strong><small>{principal.tenantId} · live</small></div><span className="live-dot"/></div>
      <nav><button className={`nav-item ${view==="documents"?"active":""}`} onClick={()=>setView("documents")}><Icon>▱</Icon> Knowledge base <small>{docs.length}</small></button><button className={`nav-item ${view==="actions"?"active":""}`} onClick={()=>setView("actions")}><Icon>◇</Icon> Outcome studio <small>{actions.length}</small></button><button className={`nav-item ${view==="integrations"?"active":""}`} onClick={()=>setView("integrations")}><Icon>⇄</Icon> Integrations <small>{integrations.length}</small></button><button className={`nav-item ${view==="agents"?"active":""}`} onClick={()=>setView("agents")}><Icon>◎</Icon> Discipline agents</button><button className={`nav-item ${view==="learning"?"active":""}`} onClick={()=>setView("learning")}><Icon>△</Icon> Learning</button><button className={`nav-item ${view==="audit"?"active":""}`} onClick={()=>setView("audit")}><Icon>✓</Icon> Audit trail</button></nav>
      <div className="left-bottom"><button className="new-chat" onClick={()=>{setMessages(messages.slice(0,1));setQuestion("");setNotice("");setActionResult(null);setView("command")}}>＋ New conversation</button><button className="profile" onClick={()=>setProfileOpen(v=>!v)}><span>CM</span><div><strong>{principal.userId}</strong><small>Operations Manager</small></div><b>•••</b></button>{profileOpen&&<div className="profile-menu"><button onClick={()=>setSettings(true)}>Workspace settings</button><button onClick={()=>{localStorage.removeItem("retailops.signedIn");setSignedIn(false)}}>Sign out</button></div>}</div>
    </aside>
    <main>
      <header className="main-head"><div>{!leftOpen&&<button className="ghost reopen" onClick={()=>setLeftOpen(true)}>☰</button>}<p className="eyebrow">{view==="command"?"COMMAND CENTER":view.toUpperCase()}</p><h2>{view==="command"?"Operational intelligence":view==="documents"?"Project knowledge":view==="actions"?"Outcome studio":view==="agents"?"Discipline agents":view==="learning"?"Verified learning":view==="integrations"?"Enterprise integrations":"Evidence & audit"}</h2></div><div className="head-actions"><span className="health"><i/> LIVE</span><button className="round" onClick={refresh}>↻</button><button className="avatar">CM</button></div></header>
      {notice&&<div className="notice"><span>{notice}</span><button onClick={()=>setNotice("")}>×</button></div>}
      {view==="command"&&<section className="command-view"><div className="welcome"><p>Good morning,</p><h1>What will you move<br/><em>forward today?</em></h1><div className="pulse-line"><span/> Grounded in {overview?.document_count??docs.length} project documents</div></div><div className="chat-stream">{messages.slice(-4).map((m,i)=><article key={i} className={`message ${m.role}`}><div className="message-role">{m.role==="assistant"?"N":"CM"}</div><div><p>{m.text}</p>{m.route&&<p className="route-meta">route: {m.route}</p>}{m.citations&&m.citations.length>0&&<div className="evidence-block">{m.citations.map((c,j)=><div key={j} className="citation-full"><strong>[{c.fused_rank??j+1}] {c.filename||"Project source"}{c.page?` p.${c.page}`:""}</strong><span className="scores">{c.vector_score!=null?`vec ${c.vector_score.toFixed(3)}`:""}{c.lexical_score!=null?` · lex ${c.lexical_score.toFixed(3)}`:""}</span>{c.excerpt&&<p>{c.excerpt}</p>}</div>)}</div>}{m.actionResult&&<pre className="outcome-json">{JSON.stringify(m.actionResult.output??m.actionResult,null,2)}</pre>}</div></article>)}{busy&&<article className="message assistant"><div className="message-role">N</div><div className="thinking"><i/><i/><i/></div></article>}</div><div className="prompt-wrap"><textarea value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();ask();}}} placeholder="Ask about inventory, compliance, operations or project evidence…"/><div className="prompt-tools"><button onClick={()=>setUploadOpen(true)}>＋ Add source</button><span>↵ to send</span><button className="send" disabled={!question||busy} onClick={()=>ask()}>↑</button></div></div><div className="quick-prompts">{["Summarise operational risks","Check promotion compliance","Create daily operations brief"].map(q=><button key={q} disabled={busy} onClick={()=>ask(q)}>{q} <span>↗</span></button>)}</div></section>}
      {view==="documents"&&<section className="content-view"><div className="section-title"><div><p className="eyebrow">PROJECT RECORD</p><h1>Knowledge base</h1><p>Every answer stays grounded in these approved sources.</p></div><button className="primary" onClick={()=>setUploadOpen(true)}>＋ Add document</button></div><div className="data-card"><div className="table-head"><span>{filteredDocs.length} of {docs.length} sources</span><input value={docSearch} onChange={e=>setDocSearch(e.target.value)} placeholder="Search sources…"/></div><table><thead><tr><th>Document</th><th>Role</th><th>Status</th><th>Chunks</th></tr></thead><tbody>{filteredDocs.map(d=><tr key={d.document_id}><td><span className="file-icon">DOC</span><strong>{d.filename}</strong></td><td>{d.doc_role||"Project record"}</td><td><span className={`status ${d.status}`}>● {d.status}</span></td><td>{d.chunk_count}</td></tr>)}</tbody></table>{!filteredDocs.length&&<div className="empty">{docs.length?"No sources match your search.":"No project sources yet. Add the first approved record."}</div>}</div></section>}
      {view==="actions"&&<section className="content-view"><div className="section-title"><div><p className="eyebrow">CONTROLLED EXECUTION</p><h1>Outcome studio</h1><p>Collect scalar inputs, confirm when required, and review the full deliverable output.</p></div></div><Actions principal={principal} onResult={(r)=>{setActionResult(r);setRightOpen(true);refresh();}}/></section>}
      {view==="agents"&&<section className="content-view"><div className="section-title"><div><p className="eyebrow">GOVERNED AGENTS</p><h1>Discipline agents</h1><p>Hat manifests, playbooks, and scoped tool access.</p></div></div><Agents principal={principal}/></section>}
      {view==="learning"&&<section className="content-view"><div className="section-title"><div><p className="eyebrow">ADAPTIVE OPS</p><h1>Verified learning</h1><p>Calibrators and exception signals grounded in verified outcomes.</p></div></div><Learning principal={principal}/></section>}
      {view==="integrations"&&<section className="content-view"><div className="section-title"><div><p className="eyebrow">SIGNATURE LAYER</p><h1>Enterprise integrations</h1><p>POS + ERP + WMS + Supplier EDI feed RetailOps AI, which publishes to the Store Digital Twin, Power BI and ServiceNow.</p></div></div><div className="integration-grid">{integrations.map(i=><article className={`integration-card status-${i.status}`} key={i.connector_id}><div className="integration-head"><h3>{i.display_name}</h3><span className={`pill pill-${i.status}`}>● {i.status}</span></div><p className="integration-desc">{i.description}</p><div className="integration-badges">{i.badges.map((b,bi)=><span key={bi} className={`badge tone-${b.tone}`}>{b.label}</span>)}</div><div className="integration-meta"><span>{i.vendor_examples.join(" · ")}</span></div><div className="integration-caps">{i.capabilities.slice(0,4).map(c=><span key={c}>{c.replace(/_/g," ")}</span>)}</div><div className="integration-sync"><small>Last sync</small><strong>{i.last_sync?new Date(i.last_sync.started_at).toLocaleString():"Never"}</strong></div>{i.connector_id==="power_bi"?<div className="integration-actions"><button disabled={integrationBusy===i.connector_id} onClick={()=>testIntegration(i.connector_id)}>{integrationBusy===i.connector_id?"…":"Test"}</button><button disabled={integrationBusy===i.connector_id} onClick={()=>exportPowerBi("export_csv")}>CSV</button><button disabled={integrationBusy===i.connector_id} onClick={()=>exportPowerBi("export_xlsx")}>XLSX</button></div>:i.mock_functional?<div className="integration-actions"><button disabled={integrationBusy===i.connector_id} onClick={()=>testIntegration(i.connector_id)}>{integrationBusy===i.connector_id?"…":"Test"}</button><button disabled={integrationBusy===i.connector_id} className="primary-mini" onClick={()=>syncIntegration(i.connector_id)}>Sync</button></div>:<div className="integration-actions"><button disabled title="Credentials required for this pilot">Test</button><button disabled title="Planned capability">Sync</button></div>}</article>)}</div></section>}
      {view==="audit"&&<section className="content-view"><div className="section-title"><div><p className="eyebrow">IMMUTABLE EVIDENCE</p><h1>Audit trail</h1><p>Trace every governed action from request to evidence.</p></div></div><div className="data-card"><table><thead><tr><th>Outcome</th><th>User</th><th>Status</th><th>Executed</th><th>Evidence</th><th>Duration</th></tr></thead><tbody>{runs.map(r=><tr key={r.request_id}><td><strong>{r.action_id.replace("retail.","").replace(/_/g," ")}</strong><small>{r.request_id.slice(0,12)}</small></td><td>{r.user_id}</td><td><span className={`status ${r.status}`}>● {r.status}</span></td><td>{new Date(r.started_at).toLocaleString()}</td><td>{r.evidence_count} refs</td><td>{r.duration_ms}ms</td></tr>)}</tbody></table></div></section>}
    </main>
    <aside className="right-panel"><div className="panel-head"><div><span className="eyebrow">OUTCOMES</span><strong>Decision pulse</strong></div><button className="ghost" onClick={()=>setRightOpen(false)}>›</button></div><div className="outcome-score"><Donut value={runs.length?Math.min(98,68+activeOutcomes*6):68}/><div><p>Operational confidence</p><strong>{activeOutcomes} verified outcomes</strong><small>Based on project evidence</small></div></div><div className="metric-grid"><div><small>DOCUMENTS</small><strong>{overview?.document_count??docs.length}</strong><span>indexed sources</span></div><div><small>ACTIONS</small><strong>{runs.length}</strong><span>total executions</span></div></div><div className="chart-card"><div><span className="eyebrow">ACTIVITY</span><b>Last 8 periods</b></div><MiniBars/></div>{actionResult&&<div className="latest-outcome"><span className="eyebrow">LATEST OUTCOME</span><div className="outcome-title"><i>✓</i><div><strong>{actionResult.action_id.replace("retail.","").replace(/_/g," ")}</strong><small>{actionResult.status} · {actionResult.evidence.length} evidence refs · {actionResult.request_id}</small></div></div>{actionResult.warnings.length>0&&<p>{actionResult.warnings.join(" · ")}</p>}<pre className="outcome-json">{JSON.stringify(actionResult.output??{},null,2)}</pre>{actionResult.evidence.length>0&&<div className="evidence-block">{actionResult.evidence.map((e,i)=><div key={i} className="citation-full"><strong>[{i+1}] {(e as Citation).filename||"evidence"}</strong>{(e as Citation).excerpt&&<p>{(e as Citation).excerpt}</p>}</div>)}</div>}</div>}<div className="exports"><span className="eyebrow">EXPORT CENTER</span><button onClick={()=>exportOutcome("pdf")}><b>PDF</b><span>Board-ready report</span><i>↓</i></button><button onClick={()=>exportOutcome("doc")}><b>DOC</b><span>Editable outcome brief</span><i>↓</i></button><button onClick={()=>exportOutcome("xls")}><b>XLS</b><span>Audit data workbook</span><i>↓</i></button></div><div className="right-foot"><span><i/> All systems operational</span><small>Kit 1.3.0</small></div></aside>
    {!rightOpen&&<button className="right-tab" onClick={()=>setRightOpen(true)}>OUTCOMES ‹</button>}
    {uploadOpen&&<div className="modal-backdrop" onMouseDown={()=>setUploadOpen(false)}><div className="modal" onMouseDown={e=>e.stopPropagation()}><button className="modal-x" onClick={()=>setUploadOpen(false)}>×</button><p className="eyebrow">KNOWLEDGE INGESTION</p><h2>Add project source</h2><p>Paste approved text. It will be chunked, indexed and isolated to this project.</p><label>File name<input value={filename} onChange={e=>setFilename(e.target.value)}/></label><label>Source content<textarea value={fileText} onChange={e=>setFileText(e.target.value)} placeholder="Paste source content…"/></label><button className="primary wide" disabled={busy||!fileText} onClick={ingest}>{busy?"Indexing…":"Index source"}</button></div></div>}
    {settings&&<div className="modal-backdrop" onMouseDown={()=>setSettings(false)}><div className="modal settings" onMouseDown={e=>e.stopPropagation()}><button className="modal-x" onClick={()=>setSettings(false)}>×</button><p className="eyebrow">ADMIN</p><h2>Workspace settings</h2><p>Identity headers are resolved and authorised by the server on every request.</p>{(["userId","tenantId","projectId"] as (keyof Principal)[]).map(k=><label key={k}>{k.replace("Id"," ID")}<input value={principal[k]} onChange={e=>setPrincipal({...principal,[k]:e.target.value})}/></label>)}<div className="admin-row"><div><strong>User access</strong><small>Operations Manager · active</small></div><span>ADMIN</span></div><button className="primary wide" onClick={()=>{localStorage.setItem("retailops.principal",JSON.stringify(principal));setSettings(false);refresh();}}>Save workspace</button></div></div>}
  </div>;
}
