export interface Principal {
  userId: string;
  tenantId: string;
  projectId: string;
}

const BASE = import.meta.env.VITE_API_URL ?? "";

function headers(p: Principal): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "X-User-Id": p.userId,
    "X-Tenant-Id": p.tenantId,
    "X-Project-Id": p.projectId,
  };
}

async function req<T>(path: string, p: Principal, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...headers(p), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export interface ActionSpec {
  action_id: string;
  name: string;
  description: string;
  risk_classification: string;
  confirmation_required: boolean;
  input_schema: { properties?: Record<string, { type?: string; enum?: string[] }>; required?: string[] };
}

export interface Citation {
  filename?: string;
  page?: number;
  excerpt?: string;
  fused_rank?: number;
  vector_score?: number;
  lexical_score?: number;
}

export interface ActionResult {
  status: string;
  request_id: string;
  action_id: string;
  output: Record<string, unknown>;
  dependencies: { kind: string; description: string }[];
  evidence: unknown[];
  warnings: string[];
  error_message?: string;
}

export interface IntegrationBadge {
  label: string;
  tone: string;
}

export interface IntegrationRun {
  run_id: string;
  kind: "test" | "sync";
  status: string;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  detail?: Record<string, unknown>;
  error_code?: string | null;
  error_message?: string | null;
}

export interface Integration {
  connector_id: string;
  display_name: string;
  category: string;
  description: string;
  vendor_examples: string[];
  capabilities: string[];
  planned_capabilities: string[];
  read_only: boolean;
  mock_functional: boolean;
  status: string;
  badges: IntegrationBadge[];
  last_test: IntegrationRun | null;
  last_sync: IntegrationRun | null;
}

export const api = {
  overview: (p: Principal) => req<{ document_count: number; recent_actions: { action_id: string; status: string; started_at: string }[]; system_health: Record<string, unknown> }>("/v1/overview", p),
  documents: (p: Principal) => req<{ documents: { document_id: string; filename: string; status: string; chunk_count: number; doc_role?: string; error?: string }[] }>("/v1/documents", p),
  ingest: (p: Principal, filename: string, text: string, doc_role?: string) =>
    req<{ document_id: string; status: string; chunk_count: number }>("/v1/documents", p, {
      method: "POST",
      body: JSON.stringify({ filename, text, doc_role }),
    }),
  ask: (p: Principal, question: string) =>
    req<{ route: string; answer: string; citations: Citation[]; action_result: ActionResult | null }>("/v1/ask", p, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  actions: (p: Principal) => req<{ actions: ActionSpec[] }>("/v1/actions", p),
  execute: (p: Principal, actionId: string, args: Record<string, unknown>, confirm: boolean) =>
    req<ActionResult>(`/v1/actions/${actionId}/execute`, p, {
      method: "POST",
      body: JSON.stringify({ arguments: args, auto_context: true, confirm }),
    }),
  audit: (p: Principal) => req<{ runs: { request_id: string; action_id: string; user_id: string; status: string; started_at: string; duration_ms: number; evidence_count: number }[] }>("/v1/audit", p),
  integrations: (p: Principal) => req<{ integrations: Integration[] }>("/v1/integrations", p),
  testIntegration: (p: Principal, connectorId: string) =>
    req<Record<string, unknown>>(`/v1/integrations/${connectorId}/test`, p, { method: "POST" }),
  syncIntegration: (p: Principal, connectorId: string, body: Record<string, unknown> = {}) =>
    req<Record<string, unknown>>(`/v1/integrations/${connectorId}/sync`, p, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  integrationRuns: (p: Principal, connectorId: string) =>
    req<{ runs: IntegrationRun[] }>(`/v1/integrations/${connectorId}/runs`, p),
};
