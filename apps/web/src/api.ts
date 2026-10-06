export type Priority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type InvestigationStatus =
  | "QUEUED"
  | "TRIAGE"
  | "INVESTIGATING"
  | "MITIGATING"
  | "PREVENTION"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface AgentSpace {
  id: string;
  name: string;
  description: string;
  accounts: string[];
  regions: string[];
  mcp_server_ids: string[];
  slack_channel?: string | null;
  created_at: string;
}

export interface Hypothesis {
  id: string;
  title: string;
  statement: string;
  status: string;
  confidence: number;
}

export interface MitigationPlan {
  strategy: string;
  steps: string[];
  validation_checks: string[];
  success_criteria: string[];
  rollback: string[];
  blast_radius: string;
}

export interface Investigation {
  id: string;
  agent_space_id: string;
  execution_id: string;
  title: string;
  description: string;
  status: InvestigationStatus;
  priority: Priority;
  starting_point: string;
  root_cause?: string | null;
  summary?: string | null;
  hypotheses: Hypothesis[];
  mitigation?: MitigationPlan | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface JournalRecord {
  id: string;
  investigation_id: string;
  record_type: string;
  title: string;
  body: string;
  actor: string;
  created_at: string;
  payload?: Record<string, unknown>;
}

export interface TopologyPayload {
  nodes: Array<{
    id: string;
    name: string;
    kind: string;
    arn?: string | null;
    attributes?: Record<string, unknown>;
  }>;
  edges: Array<{ id: string; source_id: string; target_id: string; kind: string }>;
}

export interface Runbook {
  id: string;
  title: string;
  path: string;
  tags: string[];
  content: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  body: string;
  kind: string;
  targets: string[];
}

export interface McpServer {
  id: string;
  name: string;
  endpoint: string;
  description: string;
  allowed_tools: string[];
  read_only: boolean;
  enabled: boolean;
}

export interface Recommendation {
  id: string;
  category: string;
  title: string;
  rationale: string;
  effort: string;
  impact: string;
  status: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  created_at: string;
}

export interface Health {
  status: string;
  env: string;
  bedrock: boolean;
  store: string;
  queue: string;
  circuits: Record<string, string>;
}

const headers: HeadersInit = { "content-type": "application/json" };

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { ...headers, ...(init?.headers || {}) } });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => http<Health>("/v1/health"),
  spaces: () => http<AgentSpace[]>("/v1/agent-spaces"),
  investigations: (spaceId?: string) =>
    http<Investigation[]>(spaceId ? `/v1/investigations?agent_space_id=${spaceId}` : "/v1/investigations"),
  investigation: (id: string) => http<Investigation>(`/v1/investigations/${id}`),
  journal: (id: string, after?: string) =>
    http<JournalRecord[]>(`/v1/investigations/${id}/journal${after ? `?after_id=${after}` : ""}`),
  startInvestigation: (payload: {
    agent_space_id: string;
    title: string;
    description: string;
    priority: Priority;
    starting_point: string;
  }) =>
    http<Investigation>("/v1/investigations", { method: "POST", body: JSON.stringify(payload) }),
  topology: (spaceId: string) => http<TopologyPayload>(`/v1/agent-spaces/${spaceId}/topology`),
  runbooks: (spaceId?: string) =>
    http<Runbook[]>(spaceId ? `/v1/runbooks?agent_space_id=${spaceId}` : "/v1/runbooks"),
  skills: (spaceId: string) => http<Skill[]>(`/v1/agent-spaces/${spaceId}/skills`),
  mcp: () => http<McpServer[]>("/v1/mcp/servers"),
  recommendations: (spaceId?: string) =>
    http<Recommendation[]>(spaceId ? `/v1/recommendations?agent_space_id=${spaceId}` : "/v1/recommendations"),
  chat: (id: string) => http<ChatMessage[]>(`/v1/investigations/${id}/chat`),
  sendChat: (id: string, content: string) =>
    http<ChatMessage>(`/v1/investigations/${id}/chat`, { method: "POST", body: JSON.stringify({ content }) }),
};
