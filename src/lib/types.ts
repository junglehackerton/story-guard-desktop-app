export type EntityType =
  | "character"
  | "place"
  | "organization"
  | "item"
  | "event"
  | "rule"
  | "foreshadowing";

export type IssueStatus = "open" | "accepted" | "ignored" | "deferred";

export interface Project {
  id: number;
  title: string;
  root_path: string | null;
  created_at: string;
  updated_at: string;
}

export interface StoryDocument {
  id: number;
  project_id: number;
  path: string;
  title: string;
  format: string;
  chapter_index: number;
  content_hash: string;
  content: string;
  created_at: string;
  analysis_status: "pending" | "analyzed" | "stale";
  analyzed_at: string | null;
  analysis_entity_count: number;
  analysis_relation_count: number;
  analysis_claim_count: number;
}

export interface DocumentDeleteResult {
  project_id: number;
}

export interface ProjectDeleteResult {
  project_id: number;
}

export interface EntityNode {
  id: number;
  project_id: number;
  type: EntityType;
  name: string;
  aliases: string[];
  summary: string;
  first_seen_document_id: number | null;
  mention_count: number;
  document_ids: number[];
  document_count: number;
  last_seen_document_id: number | null;
  appearance_state: "new" | "active" | "fading" | "dormant";
  visual_weight: number;
}

export interface RelationEdge {
  id: number;
  project_id: number;
  source_entity_id: number;
  target_entity_id: number;
  type: string;
  confidence: number;
  evidence_chunk_ids: number[];
  strength: number;
  is_weak: boolean;
  is_recent: boolean;
  display_label: string;
}

export interface ContinuityIssue {
  id: number;
  project_id: number;
  severity: "low" | "medium" | "high";
  category:
    | "timeline"
    | "character_state"
    | "world_rule"
    | "relationship"
    | "unresolved_foreshadowing"
    | "contradiction";
  title: string;
  description: string;
  evidence_chunk_ids: number[];
  status: IssueStatus;
}

export interface EvidenceChunk {
  id: number;
  document_id: number;
  project_id: number;
  chunk_index: number;
  text: string;
  start_offset: number;
  end_offset: number;
}

export interface RelationChange {
  id: number;
  project_id: number;
  source_entity_id: number;
  target_entity_id: number;
  source_name: string;
  target_name: string;
  previous_type: string;
  current_type: string;
  previous_document_id: number;
  current_document_id: number;
  description: string;
  evidence_chunk_ids: number[];
}

export interface GraphRange {
  start_chapter: number | null;
  end_chapter: number | null;
  document_ids: number[];
  document_count: number;
  continuity_ready: boolean;
  message: string;
}

export interface GraphPayload {
  entities: EntityNode[];
  relations: RelationEdge[];
  issues: ContinuityIssue[];
  changes: RelationChange[];
  range: GraphRange;
}

export type AnalysisStatus = "idle" | "running" | "completed" | "failed" | "cancelled";

export interface AnalysisJob {
  id: number;
  project_id: number;
  status: AnalysisStatus;
  current_step: string;
  progress: number;
  message: string;
  created_at: string;
  updated_at: string;
}

export interface EntityRelationshipDetail {
  relation: RelationEdge;
  other: EntityNode;
  direction: "outgoing" | "incoming";
  explanation: string;
}

export interface LocalAiHealth {
  ok: boolean;
  runtime: string;
  message: string;
  models: string[];
  model_dir: string;
}

export interface AppSettings {
  generation_model: string;
  embedding_model: string;
}

export interface EnvironmentStatus {
  platform: string;
  runtime_installed: boolean;
  runtime_running: boolean;
  model_dir: string;
  embedding_model: string;
  generation_model: string;
  embedding_model_ready: boolean;
  generation_model_ready: boolean;
  models: string[];
  ready: boolean;
  can_auto_install: boolean;
  install_method: string;
  message: string;
}

export interface EnvironmentSetupRequest {
  install_runtime: boolean;
  prepare_embedding_model: boolean;
  prepare_generation_model: boolean;
  embedding_model: string;
  generation_model: string;
}

export interface EnvironmentSetupProgress {
  running: boolean;
  stage: string;
  message: string;
  logs: string[];
  error: string | null;
}
