import { useEffect, useState } from "react";
import type { Principal } from "../api";
import { api, type AgentManifest } from "../api";

function playbookCounts(m: AgentManifest) {
  const pb = m.playbook;
  return {
    f: pb?.formulas?.length ?? 0,
    s: pb?.standards?.length ?? 0,
    p: pb?.procedures?.length ?? 0,
  };
}

export function Agents({ principal }: { principal: Principal }) {
  const principalKey = `${principal.tenantId}:${principal.projectId}:${principal.userId}`;
  const [hats, setHats] = useState<AgentManifest[]>([]);
  const [bases, setBases] = useState<AgentManifest[]>([]);
  const [selected, setSelected] = useState<AgentManifest | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadedKey, setLoadedKey] = useState(principalKey);

  // Reset catalog state when the workspace principal changes (render-time, not in effect).
  if (loadedKey !== principalKey) {
    setLoadedKey(principalKey);
    setHats([]);
    setBases([]);
    setSelected(null);
    setError("");
    setLoading(true);
  }

  useEffect(() => {
    let cancelled = false;
    api
      .agents(principal)
      .then((r) => {
        if (cancelled) return;
        setBases(r.bases);
        setHats(r.hats);
        setError("");
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [principal]);

  return (
    <div className="card">
      <h2>Discipline Agents</h2>
      <p className="muted">
        Base agent + discipline hats. Each hat owns formulas, standards, and procedures.
        Hats specialize RetailOps; they do not replace LangGraph or the ActionRegistry.
      </p>
      {loading && <p className="muted">Loading agent catalog…</p>}
      {error && <p className="error">{error}</p>}

      {!loading && !error && (
        <>
          <h3>Base</h3>
          <ul className="learning-list">
            {bases.map((b) => {
              const c = playbookCounts(b);
              return (
                <li key={b.agent_id}>
                  <button type="button" className="linkish" onClick={() => setSelected(b)}>
                    <strong>{b.display_name}</strong>
                  </button>
                  <div className="muted">
                    {b.summary} · playbook {c.f}F/{c.s}S/{c.p}P
                  </div>
                </li>
              );
            })}
          </ul>

          <h3>Hats ({hats.length})</h3>
          <ul className="learning-list">
            {hats.map((h) => {
              const c = playbookCounts(h);
              return (
                <li key={h.agent_id}>
                  <button type="button" className="linkish" onClick={() => setSelected(h)}>
                    <strong>{h.display_name}</strong>
                  </button>
                  <div className="muted">
                    {h.discipline} · {h.activation?.default_enabled ? "on" : "off"} · handoffs{" "}
                    {(h.handoffs || []).length} · playbook {c.f}F/{c.s}S/{c.p}P
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {selected && <PlaybookDetail agent={selected} />}
    </div>
  );
}

function PlaybookDetail({ agent }: { agent: AgentManifest }) {
  const pb = agent.playbook;
  return (
    <section className="learning-section">
      <h3>{agent.display_name}</h3>
      <p className="muted">{agent.summary}</p>

      <h4>Formulas</h4>
      <ul className="learning-list">
        {(pb?.formulas || []).map((f) => (
          <li key={f.id}>
            <strong>{f.name}</strong> <span className="muted">({f.id})</span>
            <div>
              <code>{f.expression}</code>
            </div>
            <div className="muted">
              in: {(f.inputs || []).join(", ") || "—"} · out: {(f.outputs || []).join(", ") || "—"}
              {f.implemented_by ? ` · via ${f.implemented_by}` : ""}
            </div>
          </li>
        ))}
      </ul>

      <h4>Standards</h4>
      <ul className="learning-list">
        {(pb?.standards || []).map((s) => (
          <li key={s.id}>
            <strong>{s.name}</strong> <span className="muted">[{s.kind}]</span>
            <div className="muted">{s.description}</div>
            {s.ref && <div className="muted">ref: {s.ref}</div>}
          </li>
        ))}
      </ul>

      <h4>Procedures</h4>
      <ul className="learning-list">
        {(pb?.procedures || []).map((p) => (
          <li key={p.id}>
            <strong>{p.name}</strong>
            {p.trigger && <div className="muted">trigger: {p.trigger}</div>}
            <ol className="procedure-steps">
              {(p.steps || []).map((st) => (
                <li key={st.step}>
                  {st.action}
                  {st.requires_confirmation ? " (confirm)" : ""}
                </li>
              ))}
            </ol>
            {p.handoff_to && <div className="muted">handoff → {p.handoff_to}</div>}
          </li>
        ))}
      </ul>

      <details>
        <summary className="muted">Full manifest JSON</summary>
        <pre className="codeblock">{JSON.stringify(agent, null, 2)}</pre>
      </details>
    </section>
  );
}
