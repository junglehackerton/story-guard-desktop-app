import type {
  AppSettings,
  ContinuityIssue,
  DocumentDeleteResult,
  EnvironmentSetupProgress,
  EnvironmentSetupRequest,
  EnvironmentStatus,
  EvidenceChunk,
  GraphPayload,
  IssueStatus,
  OllamaHealth,
  Project,
  StoryDocument,
} from "./types";

const API_BASE = import.meta.env.VITE_STORY_GUARD_API ?? "http://127.0.0.1:8765";
let apiToken = "";

export function setApiToken(token: string) {
  apiToken = token.trim();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = {
    "Content-Type": "application/json",
    ...(apiToken ? { "X-Story-Guard-Token": apiToken } : {}),
    ...(init?.headers ?? {}),
  };
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  settings: () => request<AppSettings>("/settings"),
  updateSettings: (settings: AppSettings) =>
    request<AppSettings>("/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  setupStatus: () => request<EnvironmentStatus>("/setup/status"),
  setupProgress: () => request<EnvironmentSetupProgress>("/setup/progress"),
  runSetup: (payload: EnvironmentSetupRequest) =>
    request<EnvironmentSetupProgress>("/setup/run", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ollamaHealth: () => request<OllamaHealth>("/health/ollama"),
  listProjects: () => request<Project[]>("/projects"),
  createProject: (title: string) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  updateProjectTitle: (projectId: number, title: string) =>
    request<Project>(`/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  importDocument: (projectId: number, path: string) =>
    request<StoryDocument>("/documents/import", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, path }),
    }),
  deleteDocument: (documentId: number) =>
    request<DocumentDeleteResult>(`/documents/${documentId}`, {
      method: "DELETE",
    }),
  listDocuments: (projectId: number) =>
    request<StoryDocument[]>(`/projects/${projectId}/documents`),
  analyzeProject: (projectId: number) =>
    request<{ entity_count: number; relation_count: number; issue_count: number }>(
      `/projects/${projectId}/analyze`,
      { method: "POST" },
    ),
  graph: (projectId: number) => request<GraphPayload>(`/projects/${projectId}/graph`),
  updateIssueStatus: (issueId: number, status: IssueStatus) =>
    request<ContinuityIssue>(`/issues/${issueId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  issueEvidence: (issueId: number) => request<EvidenceChunk[]>(`/issues/${issueId}/evidence`),
};
