import { useEffect, useState } from "react";
import type { Principal } from "../api";
import { api, type AgentManifest } from "../api";

export function Agents({ principal }: { principal: Principal }) {
  const [hats, setHats] = useState<AgentManifest[]>([]);
  const [bases, setBases] = useState<AgentManifest[]>([]);
  const [selected, setSelected] = useState<AgentManifest | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
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
        Base agent + discipline hats. Hats specialize RetailOps; they do not replace
        LangGraph or the ActionRegistry. Toggle put-off signals from the Assistant via{" "}
        <code>disabled_agents</code>.
      </p>
      {loading && <p className="muted">Loading agent catalog…</p>}
      {error && <p className="error">{error}</p>}

      {!loading && !error && (
        <>
          <h3>Base</h3>
          <ul className="learning-list">
            {bases.map((b) => (
              <li key={b.agent_id}>
                <button type="button" className="linkish" onClick={() => setSelected(b)}>
                  <strong>{b.display_name}</strong>
                </button>
                <div className="muted">{b.summary}</div>
              </li>
            ))}
          </ul>

          <h3>Hats ({hats.length})</h3>
          <ul className="learning-list">
            {hats.map((h) => (
              <li key={h.agent_id}>
                <button type="button" className="linkish" onClick={() => setSelected(h)}>
                  <strong>{h.display_name}</strong>
                </button>
                <div className="muted">
                  {h.discipline} · activation {h.activation?.mode} ·{" "}
                  {h.activation?.default_enabled ? "on" : "off"} · handoffs{" "}
                  {(h.handoffs || []).length}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {selected && (
        <section className="learning-section">
          <h3>{selected.display_name}</h3>
          <p className="muted">{selected.summary}</p>
          <pre className="codeblock">{JSON.stringify(selected, null, 2)}</pre>
        </section>
      )}
    </div>
  );
}
