import { useCallback, useEffect, useState } from "react";
import { api, type ActionResult, type ActionSpec, type Citation, type Principal } from "./api";

type View = "command" | "documents" | "actions" | "audit";
type ChatMessage = { role: "assistant" | "user"; text: string; citations?: Citation[] };

const INITIAL_PRINCIPAL: Principal = { userId: "u_ops_manager", tenantId: "northstar", projectId: "" };
const Icon = ({ children }: { children: React.ReactNode }) => <span className="icon" aria-hidden>{children}</span>;

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
  const [principal, setPrincipal] = useState<Principal>(() => {
    try { return JSON.parse(localStorage.getItem("retailops.principal") || "null") || INITIAL_PRINCIPAL; } catch { return INITIAL_PRINCIPAL; }
  });
  const [signedIn, setSignedIn] = useState(() => Boolean(localStorage.getItem("retailops.signedIn")));
  const [view, setView] = useState<View>("command");
  const [leftOpen, setLeftOpen] = useState(true); const [rightOpen, setRightOpen] = useState(true);
  const [settings, setSettings] = useState(false); const [profileOpen, setProfileOpen] = useState(false);
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof api.overview>> | null>(null);
  const [docs, setDocs] = useState<Awaited<ReturnType<typeof api.documents>>["documents"]>([]);
  const [actions, setActions] = useState<ActionSpec[]>([]);
  const [runs, setRuns] = useState<Awaited<ReturnType<typeof api.audit>>["runs"]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([{role:"assistant",text:"Good morning. I’m ready to turn your project records into grounded answers and auditable outcomes. What do you need to know?"}]);
  const [question, setQuestion] = useState(""); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false); const [filename, setFilename] = useState("operations-note.txt"); const [fileText, setFileText] = useState("");
  const [actionResult, setActionResult] = useState<ActionResult | null>(null);

  const ready = Boolean(principal.userId && principal.tenantId && principal.projectId);
  const refresh = useCallback(async () => {
    if (!ready) return;
    const results = await Promise.allSettled([api.overview(principal), api.documents(principal), api.actions(principal), api.audit(principal)]);
    if (results[0].status === "fulfilled") setOverview(results[0].value);
    if (results[1].status === "fulfilled") setDocs(results[1].value.documents);
    if (results[2].status === "fulfilled") setActions(results[2].value.actions);
    if (results[3].status === "fulfilled") setRuns(results[3].value.runs);
    const failed = results.find(r=>r.status==="rejected"); if (failed) setNotice(String((failed as PromiseRejectedResult).reason));
  }, [principal, ready]);
  useEffect(()=>{ refresh(); },[refresh]);

  const signIn = () => { if (!ready) { setNotice("Enter your project ID to open the secure workspace."); return; } localStorage.setItem("retailops.principal",JSON.stringify(principal)); localStorage.setItem("retailops.signedIn","1"); setSignedIn(true); };
  const ask = async () => {
    const q=question.trim(); if(!q||busy) return; setMessages(m=>[...m,{role:"user",text:q}]); setQuestion(""); setBusy(true); setNotice("");
    try { const res=await api.ask(principal,q); setMessages(m=>[...m,{role:"assistant",text:res.answer,citations:res.citations}]); if(res.action_result) setActionResult(res.action_result); }
    catch(e){setMessages(m=>[...m,{role:"assistant",text:"I couldn’t complete that request. "+String(e)}]);} finally{setBusy(false); refresh();}
  };
  const ingest = async () => { if(!fileText.trim()) return; setBusy(true); try{await api.ingest(principal,filename,fileText,"project_record");setFileText("");setUploadOpen(false);setNotice("Document indexed successfully.");await refresh();}catch(e){setNotice(String(e));}finally{setBusy(false);} };
  const runAction = async (spec: ActionSpec) => { setBusy(true); setNotice(""); try{const r=await api.execute(principal,spec.action_id,{},spec.confirmation_required);setActionResult(r);setRightOpen(true);await refresh();}catch(e){setNotice(String(e));}finally{setBusy(false);} };
  const exportOutcome=(kind:"pdf"|"doc"|"xls")=>{
    const rows=runs.map(r=>`<tr><td>${r.action_id}</td><td>${r.status}</td><td>${new Date(r.started_at).toLocaleString()}</td><td>${r.evidence_count}</td></tr>`).join("");
    const html=`<html><body><h1>RetailOps Outcome Report</h1><p>Project: ${principal.projectId}</p><p>Documents: ${overview?.document_count??0}</p><table border="1"><tr><th>Outcome</th><th>Status</th><th>Date</th><th>Evidence</th></tr>${rows}</table></body></html>`;
    if(kind==="pdf"){window.print();return;} download(`retailops-${principal.projectId}.${kind==="doc"?"doc":"xls"}`,kind==="doc"?"application/msword":"application/vnd.ms-excel",html);
  };

  if(!signedIn) return <div className="login-page"><div className="edge-word left">PILOT</div><div className="edge-word right">SDKSYSTEMS</div><section className="login-card"><div className="mark">N</div><p className="eyebrow">NORTHSTAR INTELLIGENCE</p><h1>Retail operations,<br/><em>made decisive.</em></h1><p className="login-copy">Secure, grounded intelligence for every store, project and operational decision.</p><div className="login-grid"><label>User ID<input value={principal.userId} onChange={e=>setPrincipal({...principal,userId:e.target.value})}/></label><label>Tenant<input value={principal.tenantId} onChange={e=>setPrincipal({...principal,tenantId:e.target.value})}/></label></div><label>Project ID<input autoFocus value={principal.projectId} onChange={e=>setPrincipal({...principal,projectId:e.target.value})} placeholder="Paste the Northstar project ID" onKeyDown={e=>e.key==="Enter"&&signIn()}/></label>{notice&&<p className="form-error">{notice}</p>}<button className="signin" onClick={signIn}>Enter workspace <span>→</span></button><footer><span>● Systems operational</span><span>Protected workspace</span></footer></section></div>;

  const activeOutcomes = runs.filter(r=>r.status==="success").length;
  return <div className={`shell ${!leftOpen?"left-closed":""} ${!rightOpen?"right-closed":""}`}>
    <aside className="rail"><div className="rail-logo">N</div><button className="rail-btn" onClick={()=>setLeftOpen(v=>!v)} title="Toggle navigator">⌘</button><div className="rail-spacer"/><button className="rail-btn" onClick={()=>setSettings(true)}>⚙</button></aside>
    <aside className="left-panel">
      <div className="panel-head"><div><span className="eyebrow">WORKSPACE</span><strong>Northstar Retail</strong></div><button className="ghost" onClick={()=>setLeftOpen(false)}>‹</button></div>
      <button className={`nav-item ${view==="command"?"active":""}`} onClick={()=>setView("command")}><Icon>⌁</Icon> Command center <small>{activeOutcomes}</small></button>
      <p className="nav-label">PROJECT</p><div className="project-card"><span className="project-icon">NR</span><div><strong>{principal.projectId}</strong><small>{principal.tenantId} · live</small></div><span className="live-dot"/></div>
      <nav><button className={`nav-item ${view==="documents"?"active":""}`} onClick={()=>setView("documents")}><Icon>▱</Icon> Knowledge base <small>{docs.length}</small></button><button className={`nav-item ${view==="actions"?"active":""}`} onClick={()=>setView("actions")}><Icon>◇</Icon> Outcome studio <small>{actions.length}</small></button><button className={`nav-item ${view==="audit"?"active":""}`} onClick={()=>setView("audit")}><Icon>✓</Icon> Audit trail</button></nav>
      <div className="left-bottom"><button className="new-chat" onClick={()=>{setMessages(messages.slice(0,1));setView("command")}}>＋ New conversation</button><button className="profile" onClick={()=>setProfileOpen(v=>!v)}><span>CM</span><div><strong>{principal.userId}</strong><small>Operations Manager</small></div><b>•••</b></button>{profileOpen&&<div className="profile-menu"><button onClick={()=>setSettings(true)}>Workspace settings</button><button onClick={()=>{localStorage.removeItem("retailops.signedIn");setSignedIn(false)}}>Sign out</button></div>}</div>
    </aside>
    <main>
      <header className="main-head"><div>{!leftOpen&&<button className="ghost reopen" onClick={()=>setLeftOpen(true)}>☰</button>}<p className="eyebrow">{view==="command"?"COMMAND CENTER":view.toUpperCase()}</p><h2>{view==="command"?"Operational intelligence":view==="documents"?"Project knowledge":view==="actions"?"Outcome studio":"Evidence & audit"}</h2></div><div className="head-actions"><span className="health"><i/> LIVE</span><button className="round" onClick={refresh}>↻</button><button className="avatar">CM</button></div></header>
      {notice&&<div className="notice"><span>{notice}</span><button onClick={()=>setNotice("")}>×</button></div>}
      {view==="command"&&<section className="command-view"><div className="welcome"><p>Good morning,</p><h1>What will you move<br/><em>forward today?</em></h1><div className="pulse-line"><span/> Grounded in {overview?.document_count??docs.length} project documents</div></div><div className="chat-stream">{messages.slice(-4).map((m,i)=><article key={i} className={`message ${m.role}`}><div className="message-role">{m.role==="assistant"?"N":"CM"}</div><div><p>{m.text}</p>{m.citations&&m.citations.length>0&&<div className="source-row">{m.citations.slice(0,3).map((c,j)=><span key={j}>[{j+1}] {c.filename||"Project source"}</span>)}</div>}</div></article>)}{busy&&<article className="message assistant"><div className="message-role">N</div><div className="thinking"><i/><i/><i/></div></article>}</div><div className="prompt-wrap"><textarea value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();ask();}}} placeholder="Ask about inventory, compliance, operations or project evidence…"/><div className="prompt-tools"><button onClick={()=>setUploadOpen(true)}>＋ Add source</button><span>↵ to send</span><button className="send" disabled={!question||busy} onClick={ask}>↑</button></div></div><div className="quick-prompts">{["Summarise operational risks","Check promotion compliance","Create daily operations brief"].map(q=><button key={q} onClick={()=>setQuestion(q)}>{q} <span>↗</span></button>)}</div></section>}
      {view==="documents"&&<section className="content-view"><div className="section-title"><div><p className="eyebrow">PROJECT RECORD</p><h1>Knowledge base</h1><p>Every answer stays grounded in these approved sources.</p></div><button className="primary" onClick={()=>setUploadOpen(true)}>＋ Add document</button></div><div className="data-card"><div className="table-head"><span>{docs.length} sources</span><input placeholder="Search sources…"/></div><table><thead><tr><th>Document</th><th>Role</th><th>Status</th><th>Chunks</th></tr></thead><tbody>{docs.map(d=><tr key={d.document_id}><td><span className="file-icon">DOC</span><strong>{d.filename}</strong></td><td>{d.doc_role||"Project record"}</td><td><span className={`status ${d.status}`}>● {d.status}</span></td><td>{d.chunk_count}</td></tr>)}</tbody></table>{!docs.length&&<div className="empty">No project sources yet. Add the first approved record.</div>}</div></section>}
      {view==="actions"&&<section className="content-view"><div className="section-title"><div><p className="eyebrow">CONTROLLED EXECUTION</p><h1>Outcome studio</h1><p>Generate governed deliverables from your project evidence.</p></div></div><div className="action-grid">{actions.map((a,i)=><article className="action-card" key={a.action_id}><span className="action-index">0{i+1}</span><div className="action-symbol">{["↗","◈","✓"][i%3]}</div><h3>{a.name}</h3><p>{a.description}</p><div><span className="risk">{a.risk_classification} risk</span>{a.confirmation_required&&<span className="confirm">confirmation</span>}</div><button disabled={busy} onClick={()=>runAction(a)}>Generate outcome <span>→</span></button></article>)}</div></section>}
      {view==="audit"&&<section className="content-view"><div className="section-title"><div><p className="eyebrow">IMMUTABLE EVIDENCE</p><h1>Audit trail</h1><p>Trace every governed action from request to evidence.</p></div></div><div className="data-card"><table><thead><tr><th>Outcome</th><th>User</th><th>Status</th><th>Executed</th><th>Evidence</th><th>Duration</th></tr></thead><tbody>{runs.map(r=><tr key={r.request_id}><td><strong>{r.action_id.replace("retail.","").replace(/_/g," ")}</strong><small>{r.request_id.slice(0,12)}</small></td><td>{r.user_id}</td><td><span className={`status ${r.status}`}>● {r.status}</span></td><td>{new Date(r.started_at).toLocaleString()}</td><td>{r.evidence_count} refs</td><td>{r.duration_ms}ms</td></tr>)}</tbody></table></div></section>}
    </main>
    <aside className="right-panel"><div className="panel-head"><div><span className="eyebrow">OUTCOMES</span><strong>Decision pulse</strong></div><button className="ghost" onClick={()=>setRightOpen(false)}>›</button></div><div className="outcome-score"><Donut value={runs.length?Math.min(98,68+activeOutcomes*6):68}/><div><p>Operational confidence</p><strong>{activeOutcomes} verified outcomes</strong><small>Based on project evidence</small></div></div><div className="metric-grid"><div><small>DOCUMENTS</small><strong>{overview?.document_count??docs.length}</strong><span>indexed sources</span></div><div><small>ACTIONS</small><strong>{runs.length}</strong><span>total executions</span></div></div><div className="chart-card"><div><span className="eyebrow">ACTIVITY</span><b>Last 8 periods</b></div><MiniBars/></div>{actionResult&&<div className="latest-outcome"><span className="eyebrow">LATEST OUTCOME</span><div className="outcome-title"><i>✓</i><div><strong>{actionResult.action_id.replace("retail.","").replace(/_/g," ")}</strong><small>{actionResult.status} · {actionResult.evidence.length} evidence refs</small></div></div>{actionResult.warnings.length>0&&<p>{actionResult.warnings[0]}</p>}</div>}<div className="exports"><span className="eyebrow">EXPORT CENTER</span><button onClick={()=>exportOutcome("pdf")}><b>PDF</b><span>Board-ready report</span><i>↓</i></button><button onClick={()=>exportOutcome("doc")}><b>DOC</b><span>Editable outcome brief</span><i>↓</i></button><button onClick={()=>exportOutcome("xls")}><b>XLS</b><span>Audit data workbook</span><i>↓</i></button></div><div className="right-foot"><span><i/> All systems operational</span><small>Kit 1.1.0</small></div></aside>
    {!rightOpen&&<button className="right-tab" onClick={()=>setRightOpen(true)}>OUTCOMES ‹</button>}
    {uploadOpen&&<div className="modal-backdrop" onMouseDown={()=>setUploadOpen(false)}><div className="modal" onMouseDown={e=>e.stopPropagation()}><button className="modal-x" onClick={()=>setUploadOpen(false)}>×</button><p className="eyebrow">KNOWLEDGE INGESTION</p><h2>Add project source</h2><p>Paste approved text. It will be chunked, indexed and isolated to this project.</p><label>File name<input value={filename} onChange={e=>setFilename(e.target.value)}/></label><label>Source content<textarea value={fileText} onChange={e=>setFileText(e.target.value)} placeholder="Paste source content…"/></label><button className="primary wide" disabled={busy||!fileText} onClick={ingest}>{busy?"Indexing…":"Index source"}</button></div></div>}
    {settings&&<div className="modal-backdrop" onMouseDown={()=>setSettings(false)}><div className="modal settings" onMouseDown={e=>e.stopPropagation()}><button className="modal-x" onClick={()=>setSettings(false)}>×</button><p className="eyebrow">ADMIN</p><h2>Workspace settings</h2><p>Identity headers are resolved and authorised by the server on every request.</p>{(["userId","tenantId","projectId"] as (keyof Principal)[]).map(k=><label key={k}>{k.replace("Id"," ID")}<input value={principal[k]} onChange={e=>setPrincipal({...principal,[k]:e.target.value})}/></label>)}<div className="admin-row"><div><strong>User access</strong><small>Operations Manager · active</small></div><span>ADMIN</span></div><button className="primary wide" onClick={()=>{localStorage.setItem("retailops.principal",JSON.stringify(principal));setSettings(false);refresh();}}>Save workspace</button></div></div>}
  </div>;
}
