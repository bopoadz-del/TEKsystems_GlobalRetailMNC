import { useEffect, useState, type ReactNode } from "react";
import type { Principal } from "../api";
import { api, type LearningProfile } from "../api";

function ConfidenceBadge({ value }: { value?: string }) {
  const v = (value || "low").toLowerCase();
  return <span className={`badge conf-${v}`}>{v}</span>;
}

export function Learning({ principal }: { principal: Principal }) {
  const [profiles, setProfiles] = useState<LearningProfile[]>([]);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .learningSummary(principal)
      .then((r) => {
        if (!cancelled) {
          setProfiles(r.profiles);
          setError("");
        }
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

  const byModule = (module: string) => profiles.filter((p) => p.module === module);

  return (
    <div className="card">
      <h2>Learning</h2>
      <p className="muted">
        Advisory-only outcome learning. Profiles are tenant/project scoped and never
        overwrite operational source systems automatically.
      </p>
      {loading && <p className="muted">Loading learning profiles…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && profiles.length === 0 && (
        <p className="muted">No verified learning profiles for this project yet.</p>
      )}

      <Section
        title="Demand / reorder recommendations"
        rows={byModule("demand_reorder")}
        render={(p) => (
          <>
            <div>
              <strong>{p.entity_key}</strong> <ConfidenceBadge value={p.confidence} />
            </div>
            <div className="muted">
              samples={p.sample_count} · v{p.version} · ROP {String(p.metrics.current_reorder_point)} →{" "}
              {String(p.metrics.recommended_reorder_point)} · period{" "}
              {p.source_period_start || "—"} → {p.source_period_end || "—"}
            </div>
          </>
        )}
      />
      <Section
        title="Supplier reliability"
        rows={byModule("supplier_fulfilment")}
        render={(p) => (
          <>
            <div>
              <strong>{p.entity_key}</strong> <ConfidenceBadge value={p.confidence} />
            </div>
            <div className="muted">
              {String(p.metrics.reliability_classification)} · OTIF{" "}
              {String(p.metrics.otif_percentage)} · fill {String(p.metrics.fill_rate)} ·
              samples={p.sample_count} · v{p.version}
            </div>
          </>
        )}
      />
      <Section
        title="Promotion effectiveness"
        rows={byModule("promotion_effectiveness")}
        render={(p) => (
          <>
            <div>
              <strong>{p.entity_key}</strong> <ConfidenceBadge value={p.confidence} />
            </div>
            <div className="muted">
              unit uplift {String(p.metrics.unit_uplift_percentage)}% · score{" "}
              {String(p.metrics.effectiveness_score)} · samples={p.sample_count} · v{p.version}
            </div>
          </>
        )}
      />
      <Section
        title="Store exception patterns"
        rows={byModule("store_exceptions")}
        render={(p) => (
          <>
            <div>
              <strong>{p.entity_key}</strong> <ConfidenceBadge value={p.confidence} />
            </div>
            <div className="muted">
              risk {String(p.metrics.severity_weighted_risk_score)} · top{" "}
              {JSON.stringify(p.metrics.top_exception_patterns || []).slice(0, 120)} · samples=
              {p.sample_count} · v{p.version}
            </div>
          </>
        )}
      />
    </div>
  );
}

function Section({
  title,
  rows,
  render,
}: {
  title: string;
  rows: LearningProfile[];
  render: (p: LearningProfile) => ReactNode;
}) {
  return (
    <section className="learning-section">
      <h3>{title}</h3>
      {rows.length === 0 && <p className="muted">No profiles.</p>}
      <ul className="learning-list">
        {rows.map((p) => (
          <li key={p.id}>{render(p)}</li>
        ))}
      </ul>
    </section>
  );
}
