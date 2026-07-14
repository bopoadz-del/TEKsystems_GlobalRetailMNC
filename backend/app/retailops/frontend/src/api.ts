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

export interface LearningProfile {
  id: string;
  module: string;
  entity_type: string;
  entity_key: string;
  metrics: Record<string, unknown>;
  sample_count: number;
  confidence: string;
  source_period_start?: string | null;
  source_period_end?: string | null;
  version: number;
  advisory_only?: boolean;
}

export interface AgentManifest {
  agent_id: string;
  kind: string;
  display_name: string;
  discipline: string;
  extends?: string | null;
  summary?: string;
  activation?: {
    mode?: string;
    default_enabled?: boolean;
    triggers?: { type: string; value: string }[];
    put_off_by?: string[];
  };
  handoffs?: { to_agent_id: string; when: string; carry?: string[] }[];
  memory?: Record<string, unknown>;
  verification?: Record<string, unknown>;
  failure_policy?: Record<string, unknown>;
  playbook?: {
    formulas?: {
      id: string;
      name: string;
      expression: string;
      inputs?: string[];
      outputs?: string[];
      implemented_by?: string | null;
      unit?: string | null;
      notes?: string;
    }[];
    standards?: {
      id: string;
      name: string;
      kind: string;
      ref?: string;
      must_cite?: boolean;
      description?: string;
    }[];
    procedures?: {
      id: string;
      name: string;
      trigger?: string;
      handoff_to?: string | null;
      requires_confirmation?: boolean;
      steps?: { step: number; action: string; requires_confirmation?: boolean }[];
    }[];
  };
  allowed_actions?: string[];
  composed_from?: string[];
  [key: string]: unknown;
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
    req<{ route: string; answer: string; citations: Citation[]; action_result: ActionResult | null; execution_plan?: Record<string, unknown> }>("/v1/ask", p, {
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
  learningSummary: (p: Principal, module?: string) =>
    req<{ advisory_only: boolean; count: number; profiles: LearningProfile[] }>(
      `/v1/learning/summary${module ? `?module=${encodeURIComponent(module)}` : ""}`,
      p,
    ),
  learningProfiles: (p: Principal) =>
    req<{ advisory_only: boolean; count: number; profiles: LearningProfile[] }>("/v1/learning/profiles", p),
  agents: (p: Principal, composed = true) =>
    req<{ vendor_neutral: boolean; bases: AgentManifest[]; hats: AgentManifest[]; hat_count: number }>(
      `/v1/agents?composed=${composed ? "true" : "false"}`,
      p,
    ),
  agent: (p: Principal, agentId: string) =>
    req<AgentManifest>(`/v1/agents/${encodeURIComponent(agentId)}`, p),
};
