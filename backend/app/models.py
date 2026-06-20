from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


EntityType = Literal[
    "character",
    "place",
    "organization",
    "item",
    "event",
    "rule",
    "foreshadowing",
]

IssueCategory = Literal[
    "timeline",
    "character_state",
    "world_rule",
    "relationship",
    "unresolved_foreshadowing",
    "contradiction",
]

IssueStatus = Literal["open", "accepted", "ignored", "deferred"]


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ProjectUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class Project(BaseModel):
    id: int
    title: str
    root_path: str | None = None
    created_at: str
    updated_at: str


class DocumentImport(BaseModel):
    project_id: int
    path: str


class DocumentDeleteResult(BaseModel):
    project_id: int


class StoryDocument(BaseModel):
    id: int
    project_id: int
    path: str
    title: str
    format: str
    chapter_index: int
    content_hash: str
    content: str
    created_at: str


class EntityNode(BaseModel):
    id: int
    project_id: int
    type: EntityType
    name: str
    aliases: list[str] = []
    summary: str
    first_seen_document_id: int | None = None
    mention_count: int = 0
    document_ids: list[int] = []
    document_count: int = 0
    last_seen_document_id: int | None = None
    appearance_state: Literal["new", "active", "fading", "dormant"] = "active"
    visual_weight: float = 0.5


class RelationEdge(BaseModel):
    id: int
    project_id: int
    source_entity_id: int
    target_entity_id: int
    type: str
    confidence: float = 0.7
    evidence_chunk_ids: list[int] = []
    strength: float = 0.5
    is_weak: bool = False
    is_recent: bool = True
    display_label: str = ""


class ContinuityIssue(BaseModel):
    id: int
    project_id: int
    severity: Literal["low", "medium", "high"]
    category: IssueCategory
    title: str
    description: str
    evidence_chunk_ids: list[int] = []
    status: IssueStatus = "open"


class EvidenceChunk(BaseModel):
    id: int
    document_id: int
    project_id: int
    chunk_index: int
    text: str


class GraphPayload(BaseModel):
    entities: list[EntityNode]
    relations: list[RelationEdge]
    issues: list[ContinuityIssue]


class AnalysisStatus(str, Enum):
    idle = "idle"
    running = "running"
    completed = "completed"
    failed = "failed"


class AnalysisJob(BaseModel):
    id: int
    project_id: int
    status: AnalysisStatus
    message: str
    created_at: str
    updated_at: str


class LocalAiHealth(BaseModel):
    ok: bool
    runtime: str
    message: str
    models: list[str] = []
    model_dir: str = ""


class AppSettings(BaseModel):
    generation_model: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    embedding_model: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf"


class EnvironmentStatus(BaseModel):
    platform: str
    runtime_installed: bool
    runtime_running: bool
    model_dir: str
    embedding_model: str
    generation_model: str
    embedding_model_ready: bool
    generation_model_ready: bool
    models: list[str] = []
    ready: bool
    can_auto_install: bool
    install_method: str
    message: str


class EnvironmentSetupRequest(BaseModel):
    install_runtime: bool = False
    prepare_embedding_model: bool = True
    prepare_generation_model: bool = True
    embedding_model: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    generation_model: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf"


class EnvironmentSetupProgress(BaseModel):
    running: bool
    stage: str
    message: str
    logs: list[str] = []
    error: str | None = None
