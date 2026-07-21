import { useState } from "react";
import { api, type Citation, type Principal } from "../api";

const PUT_OFF_OPTIONS = [
  { id: "disable:roster", label: "Put off roster" },
  { id: "disable:accounting", label: "Put off accounting" },
  { id: "disable:hr", label: "Put off HR" },
  { id: "disable:marketing", label: "Put off marketing" },
  { id: "disable:inventory", label: "Put off inventory" },
];

export function Assistant({ principal }: { principal: Principal }) {
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState("");
  const [route, setRoute] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [planProjectId, setPlanProjectId] = useState(principal.projectId);
  const [disabled, setDisabled] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Clear the prior project's execution plan when the project changes.
  if (planProjectId !== principal.projectId) {
    setPlanProjectId(principal.projectId);
    setPlan(null);
  }

  const toggle = (id: string) => {
    setDisabled((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const ask = async () => {
    setBusy(true);
    setError("");
    setAnswer("");
    setPlan(null);
    try {
      const res = await api.ask(principal, q, disabled);
      setAnswer(res.answer);
      setRoute(res.route);
      setCitations(res.citations);
      setPlan(res.execution_plan ?? null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>Assistant</h2>
      <input
        type="text"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Ask a document question, e.g. What is the stock discrepancy escalation process?"
        onKeyDown={(e) => e.key === "Enter" && q && ask()}
      />
      <div className="putoff-row">
        {PUT_OFF_OPTIONS.map((opt) => (
          <label key={opt.id} className="muted">
            <input
              type="checkbox"
              checked={disabled.includes(opt.id)}
              onChange={() => toggle(opt.id)}
            />{" "}
            {opt.label}
          </label>
        ))}
      </div>
      <div style={{ marginTop: 8 }}>
        <button className="primary" disabled={busy || !q} onClick={ask}>
          {busy ? "Thinking…" : "Ask"}
        </button>
        {route && <span className="muted"> route: {route}</span>}
      </div>
      {error && <p className="error">{error}</p>}
      {answer && (
        <div style={{ marginTop: 12 }}>
          <p>{answer}</p>
          {citations.length > 0 ? (
            <>
              <h2>Citations</h2>
              {citations.map((c, i) => (
                <div key={i} className="citation">
                  [{c.fused_rank ?? i + 1}] {c.excerpt}
                  <div className="muted">
                    {c.filename}
                    {c.page ? ` p.${c.page}` : ""}
                    {c.vector_score != null ? ` · vec ${c.vector_score.toFixed(3)}` : ""}
                    {c.lexical_score != null ? ` · lex ${c.lexical_score.toFixed(3)}` : ""}
                  </div>
                </div>
              ))}
            </>
          ) : (
            <p className="muted">No citations — the assistant will not fabricate an answer.</p>
          )}
        </div>
      )}
      {plan && (
        <details className="learning-section" open>
          <summary>
            Execution plan
            {plan.primary_agent_id ? ` · ${(plan.primary_agent_id as string)}` : ""}
          </summary>
          <div className="muted">
            intent: {String(plan.primary_intent)} · confidence: {String(plan.confidence)} ·
            actions: {JSON.stringify(plan.recommended_action_ids || [])}
          </div>
          {Array.isArray(plan.handoff_tips) && plan.handoff_tips.length > 0 && (
            <div className="muted">
              handoffs:{" "}
              {(plan.handoff_tips as { to_agent_id: string }[])
                .map((h) => h.to_agent_id)
                .join(", ")}
            </div>
          )}
          {plan.playbook_refs != null && (
            <div className="muted">
              playbook: {JSON.stringify(plan.playbook_refs)}
            </div>
          )}
          <pre className="codeblock">{JSON.stringify(plan, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
