import { useEffect, useState } from "react";
import { api, type ActionResult, type ActionSpec, type Principal } from "../api";

function downloadBase64(b64: string, filename: string, contentType: string) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: contentType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function omitBase64(output: Record<string, unknown>) {
  const { document_base64: _drop, ...rest } = output;
  return rest;
}

function ActionCard({ principal, spec }: { principal: Principal; spec: ActionSpec }) {
  const props = spec.input_schema.properties ?? {};
  const required = new Set(spec.input_schema.required ?? []);
  // Only scalar inputs are rendered as form fields; complex inputs (records,
  // rows, rules, evidence) are auto-populated from project documents.
  const scalarKeys = Object.keys(props).filter((k) => {
    const t = props[k].type;
    return t === "string" || t === "number" || t === "integer" || t === "boolean" || props[k].enum;
  });

  const [values, setValues] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<ActionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const args: Record<string, unknown> = {};
      for (const k of scalarKeys) {
        if (values[k] !== undefined && values[k] !== "") args[k] = values[k];
      }
      setResult(await api.execute(principal, spec.action_id, args, confirm));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>{spec.name}</h2>
      <p className="muted">{spec.description}</p>
      <p className="muted">
        <code>{spec.action_id}</code> · risk: {spec.risk_classification}
      </p>
      {scalarKeys.map((k) => (
        <div key={k}>
          <label>{k}{required.has(k) ? " *" : ""}</label>
          {props[k].enum ? (
            <select value={values[k] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}>
              <option value="">(auto)</option>
              {props[k].enum!.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={values[k] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
            />
          )}
        </div>
      ))}
      {spec.confirmation_required && (
        <label style={{ marginTop: 8 }}>
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> Confirm this action
        </label>
      )}
      <div style={{ marginTop: 8 }}>
        <button className="primary" disabled={busy} onClick={run}>
          {busy ? "Running…" : "Run action"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <div style={{ marginTop: 12 }}>
          <span className={`badge ${result.status}`}>{result.status}</span>
          {result.error_message && <span className="muted"> {result.error_message}</span>}
          {result.status === "dependency_required" && (
            <ul>
              {result.dependencies.map((d, i) => (
                <li key={i}>{d.description}</li>
              ))}
            </ul>
          )}
          {result.status === "success" && (
            <>
              <p className="muted">{result.evidence.length} evidence reference(s) · request {result.request_id}</p>
              {typeof result.output.document_base64 === "string" && (
                <p>
                  <button
                    className="primary"
                    type="button"
                    onClick={() =>
                      downloadBase64(
                        String(result.output.document_base64),
                        String(result.output.filename || "export.bin"),
                        String(result.output.content_type || "application/octet-stream"),
                      )
                    }
                  >
                    Download {String(result.output.filename || "file")}
                  </button>
                  <span className="muted">
                    {" "}
                    · {String(result.output.format || "")} · {String(result.output.byte_size || "")} bytes
                  </span>
                </p>
              )}
              <pre>{JSON.stringify(omitBase64(result.output), null, 2)}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function Actions({ principal }: { principal: Principal }) {
  const [specs, setSpecs] = useState<ActionSpec[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.actions(principal).then((d) => setSpecs(d.actions)).catch((e) => setError(String(e)));
  }, [principal]);

  if (error) return <div className="card error">{error}</div>;
  return (
    <div>
      {specs.map((s) => (
        <ActionCard key={s.action_id} principal={principal} spec={s} />
      ))}
      {specs.length === 0 && <div className="card muted">No actions available.</div>}
    </div>
  );
}
