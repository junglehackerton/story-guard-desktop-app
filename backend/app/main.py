from __future__ import annotations

import asyncio
import hmac
import os
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "False")

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.config import chroma_path, database_path
from backend.app.database import Database
from backend.app.models import (
    AppSettings,
    ContinuityIssue,
    DocumentDeleteResult,
    DocumentImport,
    EnvironmentSetupProgress,
    EnvironmentSetupRequest,
    EnvironmentStatus,
    EvidenceChunk,
    GraphPayload,
    IssueStatus,
    OllamaHealth,
    Project,
    ProjectCreate,
    ProjectUpdate,
    StoryDocument,
)
from backend.app.pipeline.analyzer import StoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.local_llm import LocalLlmExtractor
from backend.app.services.environment_setup import EnvironmentSetupManager
from backend.app.services.ollama import OllamaClient
from backend.app.services.parser import UnsupportedDocumentFormat, read_document, split_chunks
from backend.app.services.rag import RagService
from backend.app.services.vector_store import VectorIndex


database = Database(database_path())
repository = StoryRepository(database)
ollama = OllamaClient()
vector_index = VectorIndex(chroma_path())


def save_environment_settings(embedding_model: str, generation_model: str) -> None:
    repository.set_setting("embedding_model", embedding_model)
    repository.set_setting("generation_model", generation_model)


setup_manager = EnvironmentSetupManager(save_environment_settings)

app = FastAPI(title="Story Guard API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://tauri.localhost",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_local_api_token(request: Request, call_next):
    expected_token = os.getenv("STORY_GUARD_API_TOKEN", "").strip()
    if not expected_token or request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)

    header_token = request.headers.get("x-story-guard-token", "").strip()
    authorization = request.headers.get("authorization", "").strip()
    bearer_token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if hmac.compare_digest(header_token, expected_token) or hmac.compare_digest(
        bearer_token,
        expected_token,
    ):
        return await call_next(request)

    return JSONResponse(status_code=401, content={"detail": "로컬 API 인증 토큰이 필요합니다."})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/settings", response_model=AppSettings)
def get_settings() -> AppSettings:
    return AppSettings(
        generation_model=repository.get_setting("generation_model", ""),
        embedding_model=repository.get_setting("embedding_model", "embeddinggemma") or "embeddinggemma",
    )


@app.put("/settings", response_model=AppSettings)
def update_settings(payload: AppSettings) -> AppSettings:
    repository.set_setting("generation_model", payload.generation_model.strip())
    repository.set_setting("embedding_model", payload.embedding_model.strip() or "embeddinggemma")
    return get_settings()


@app.get("/health/ollama", response_model=OllamaHealth)
async def ollama_health() -> OllamaHealth:
    return await ollama.health()


@app.get("/setup/status", response_model=EnvironmentStatus)
def setup_status() -> EnvironmentStatus:
    return setup_manager.status()


@app.get("/setup/progress", response_model=EnvironmentSetupProgress)
def setup_progress() -> EnvironmentSetupProgress:
    return setup_manager.progress()


@app.post("/setup/run", response_model=EnvironmentSetupProgress)
def run_setup(payload: EnvironmentSetupRequest) -> EnvironmentSetupProgress:
    return setup_manager.start(payload)


@app.post("/projects", response_model=Project)
def create_project(payload: ProjectCreate) -> Project:
    return repository.create_project(payload.title)


@app.get("/projects", response_model=list[Project])
def list_projects() -> list[Project]:
    projects = repository.list_projects()
    if projects:
        return projects
    return [repository.create_project("새 작품")]


@app.patch("/projects/{project_id}", response_model=Project)
def update_project(project_id: int, payload: ProjectUpdate) -> Project:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="작품 제목을 입력해 주세요.")
    try:
        return repository.update_project_title(project_id, title)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="작품을 찾을 수 없습니다.") from error


@app.post("/documents/import", response_model=StoryDocument)
async def import_document(payload: DocumentImport) -> StoryDocument:
    path = Path(payload.path)
    try:
        content, file_format, content_hash = read_document(path)
    except UnsupportedDocumentFormat as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.") from error

    document = repository.add_document(
        project_id=payload.project_id,
        path=path,
        title=path.stem,
        file_format=file_format,
        content_hash=content_hash,
        content=content,
    )
    settings = get_settings()
    request_rag = RagService(chroma_path(), embedding_model=settings.embedding_model)
    rag_chunks = request_rag.split_text(content, document.id, payload.project_id)
    chunks = [chunk.text for chunk in rag_chunks] or split_chunks(content)
    chunk_ids = repository.replace_chunks(payload.project_id, document.id, chunks)
    repository.clear_analysis(payload.project_id)
    if chunks:
        asyncio.create_task(
            index_document_chunks(payload.project_id, chunk_ids, chunks, settings.embedding_model)
        )
    return document


async def index_document_chunks(
    project_id: int,
    chunk_ids: list[int],
    chunks: list[str],
    embedding_model: str,
) -> None:
    try:
        ollama_status = await ollama.health()
        if not ollama_status.ok:
            return
        request_rag = RagService(chroma_path(), embedding_model=embedding_model)
        try:
            await asyncio.to_thread(request_rag.index_chunks, project_id, chunk_ids, chunks)
        except Exception:
            embeddings = await ollama.embed(chunks, model=embedding_model)
            await asyncio.to_thread(vector_index.upsert_texts, project_id, chunk_ids, chunks, embeddings)
    except Exception:
        return


@app.get("/projects/{project_id}/documents", response_model=list[StoryDocument])
def list_documents(project_id: int) -> list[StoryDocument]:
    return repository.list_documents(project_id)


@app.delete("/documents/{document_id}", response_model=DocumentDeleteResult)
def delete_document(document_id: int) -> DocumentDeleteResult:
    try:
        project_id = repository.delete_document(document_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="원고를 찾을 수 없습니다.") from error
    return DocumentDeleteResult(project_id=project_id)


@app.post("/projects/{project_id}/analyze")
def analyze_project(project_id: int) -> dict[str, int]:
    settings = get_settings()
    analyzer = StoryAnalyzer(
        repository,
        RagService(chroma_path(), embedding_model=settings.embedding_model),
        LocalLlmExtractor(model=settings.generation_model),
    )
    result = analyzer.analyze_project(project_id)
    return {
        "entity_count": result.entity_count,
        "relation_count": result.relation_count,
        "issue_count": result.issue_count,
    }


@app.get("/projects/{project_id}/graph", response_model=GraphPayload)
def project_graph(project_id: int) -> GraphPayload:
    return repository.graph(project_id)


@app.patch("/issues/{issue_id}/status", response_model=ContinuityIssue)
def update_issue_status(issue_id: int, payload: dict[str, IssueStatus]) -> ContinuityIssue:
    status = payload.get("status")
    if status not in {"open", "accepted", "ignored", "deferred"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 이슈 상태입니다.")
    try:
        return repository.update_issue_status(issue_id, status)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="이슈를 찾을 수 없습니다.") from error


@app.get("/issues/{issue_id}/evidence", response_model=list[EvidenceChunk])
def issue_evidence(issue_id: int) -> list[EvidenceChunk]:
    with database.connect() as connection:
        row = connection.execute("SELECT evidence_chunk_ids FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="이슈를 찾을 수 없습니다.")
    import json

    chunk_ids = json.loads(row["evidence_chunk_ids"] or "[]")
    return [EvidenceChunk(**chunk) for chunk in repository.get_chunks(chunk_ids)]


def main() -> None:
    import uvicorn

    port = int(os.getenv("STORY_GUARD_BACKEND_PORT", "8765"))
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
