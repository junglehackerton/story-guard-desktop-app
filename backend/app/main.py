from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "False")

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from backend.app.chatgpt_routes import router as chatgpt_router, connection as chatgpt_connection
from backend.app.config import chroma_path, database_path, models_path
from backend.app.database import Database
from backend.app.models import (
    AnalysisJob,
    AnalysisStatus,
    AppSettings,
    ContinuityIssue,
    DocumentDeleteResult,
    DocumentImport,
    DocumentReplace,
    EnvironmentSetupProgress,
    EnvironmentSetupRequest,
    EnvironmentStatus,
    EvidenceChunk,
    GraphPayload,
    IssueStatus,
    LocalAiHealth,
    Project,
    ProjectCreate,
    ProjectDeleteResult,
    ProjectUpdate,
    StoryDocument,
    StorySetting,
    StorySettingCreate,
    StorySettingUpdate,
    ForeshadowingStatus,
    ForeshadowingStatusUpdate,
)
from backend.app.pipeline.analyzer import StoryAnalyzer
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer, count_review_windows
from backend.app.chatgpt_routes import ManuscriptAnalysisRequest
from backend.app.repository import StoryRepository
from backend.app.services.environment_setup import EnvironmentSetupManager
from backend.app.services.local_ai import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_GENERATION_MODEL,
    LocalAiRuntime,
)
from backend.app.services.local_llm import LocalLlmExtractor
from backend.app.services.parser import UnsupportedDocumentFormat, read_document, split_chunks
from backend.app.services.rag import RagService
from backend.app.services.embedding_models import GemmaEmbeddings


database = Database(database_path())
repository = StoryRepository(database)
local_ai = LocalAiRuntime(models_path())


def save_environment_settings(embedding_model: str, generation_model: str) -> None:
    repository.set_setting("embedding_model", embedding_model)
    repository.set_setting("generation_model", generation_model)


def load_environment_settings() -> AppSettings:
    generation_model = repository.get_setting("generation_model", DEFAULT_GENERATION_MODEL).strip()
    if (
        not generation_model
        or not generation_model.lower().endswith(".gguf")
    ):
        generation_model = DEFAULT_GENERATION_MODEL
    embedding_model = repository.get_setting("embedding_model", DEFAULT_EMBEDDING_MODEL).strip()
    if embedding_model not in {DEFAULT_EMBEDDING_MODEL, "embeddinggemma-300m"}:
        embedding_model = DEFAULT_EMBEDDING_MODEL
    return AppSettings(
        generation_model=generation_model,
        embedding_model=embedding_model or DEFAULT_EMBEDDING_MODEL,
    )


setup_manager = EnvironmentSetupManager(save_environment_settings, load_environment_settings)

app = FastAPI(title="Story Guard API", version="0.1.0")


class DemoAnalysisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)


_demo_visitors: set[str] = set()
_demo_lock = threading.Lock()


@app.post("/api/demo/analyze")
async def demo_analyze(payload: DemoAnalysisRequest, request: Request, response: Response) -> dict[str, str]:
    """Run the single public-demo review against pre-indexed sample context."""
    visitor = request.cookies.get("story_guard_demo_visitor") or secrets.token_urlsafe(24)
    with _demo_lock:
        if visitor in _demo_visitors:
            raise HTTPException(status_code=429, detail="이 브라우저는 데모 GPT 분석을 이미 사용했습니다.")
    api_key = os.getenv("STORY_GUARD_DEMO_OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="데모 GPT 키가 아직 설정되지 않았습니다. 미리 색인된 결과는 계속 탐색할 수 있습니다.")
    prompt = (
        "한국어 소설의 설정 연결을 검토하세요. 제공된 원문과 새 문장만 사용하고 3문장 이내로 답하세요. "
        "새 문장이 기존 설정과 충돌하는지, 확인할 근거가 무엇인지 설명하세요.\n"
        "미리 색인된 원문:\n"
        "문을 열기 전에 반드시 두 번 두드릴 것. 윤해주는 철거 직전의 백로호텔 정문을 두 번 두드렸다.\n"
        "민규백은 지하 문서금고 계약의 취소를 요구했고, 서우는 계약서를 보관하고 있다.\n"
        f"새 문장:\n{payload.text}"
    )
    try:
        import httpx
        async with httpx.AsyncClient(timeout=45) as client:
            result = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"authorization": f"Bearer {api_key}"},
                json={"model": os.getenv("STORY_GUARD_DEMO_MODEL", "gpt-4o-mini"), "input": prompt, "max_output_tokens": 220},
            )
            result.raise_for_status()
            data = result.json()
        summary = data.get("output_text", "").strip()
        if not summary:
            for item in data.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"}:
                        summary += content.get("text", "")
        summary = summary.strip()
        if not summary:
            raise RuntimeError("GPT 응답이 비어 있습니다.")
    except Exception as error:
        logging.getLogger(__name__).warning("demo GPT request failed: %s", error)
        raise HTTPException(status_code=502, detail="데모 GPT 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.") from error
    with _demo_lock:
        _demo_visitors.add(visitor)
    response.set_cookie("story_guard_demo_visitor", visitor, max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return {"summary": summary}

# Importing several chapters in quick succession should produce one derived
# index build.  Starting a sync for every file reloads the local embedding
# runtime repeatedly and makes bulk imports look hung on laptop hardware.
_index_tasks: dict[int, asyncio.Task] = {}
_index_generations: dict[int, int] = defaultdict(int)


def schedule_project_index(project_id: int, embedding_model: str) -> None:
    """Coalesce bursty document imports into one debounced index sync."""
    _index_generations[project_id] += 1
    task = _index_tasks.get(project_id)
    if task is None or task.done():
        _index_tasks[project_id] = asyncio.create_task(
            _run_scheduled_project_index(project_id, embedding_model)
        )


async def _run_scheduled_project_index(project_id: int, embedding_model: str) -> None:
    task = asyncio.current_task()
    seen_generation = -1
    try:
        while True:
            # Allow a multi-file Finder drop/API burst to settle before the
            # expensive model is loaded.  The analysis endpoint still calls
            # sync_project synchronously, so this remains only a warm cache.
            await asyncio.sleep(0.35)
            seen_generation = _index_generations[project_id]
            request_rag = RagService(
                chroma_path(), embedding_model=embedding_model, repository=repository
            )
            await asyncio.to_thread(request_rag.sync_project, project_id)
            if seen_generation == _index_generations[project_id]:
                return
    except Exception:
        logging.getLogger(__name__).exception("원고 검색 인덱스 준비 실패: project=%s", project_id)
    finally:
        if _index_tasks.get(project_id) is task:
            _index_tasks.pop(project_id, None)
app.include_router(chatgpt_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # Keep an alternate local Vite port available for isolated UI smoke
        # tests without weakening the API to arbitrary web origins.
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://tauri.localhost",
        "tauri://localhost",
    ],
    # Vite may select any free localhost port during a parallel smoke test.
    # Keep the exception limited to loopback origins rather than allowing
    # arbitrary web sites to call the local API.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
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


@app.get("/health/ready")
def authenticated_health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/shutdown")
def shutdown(background_tasks: BackgroundTasks) -> dict[str, str]:
    background_tasks.add_task(shutdown_process)
    return {"status": "stopping"}


def shutdown_process() -> None:
    time.sleep(0.2)
    chatgpt_connection.transport.close()
    GemmaEmbeddings.release()
    os._exit(0)


def start_parent_process_monitor() -> None:
    parent_pid = os.getenv("STORY_GUARD_PARENT_PID", "").strip()
    if not parent_pid:
        return
    try:
        pid = int(parent_pid)
    except ValueError:
        return
    monitor = threading.Thread(target=monitor_parent_process, args=(pid,), daemon=True)
    monitor.start()


def monitor_parent_process(parent_pid: int) -> None:
    while True:
        time.sleep(1.0)
        if not process_exists(parent_pid):
            os._exit(0)


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@app.get("/settings", response_model=AppSettings)
def get_settings() -> AppSettings:
    return load_environment_settings()


@app.put("/settings", response_model=AppSettings)
def update_settings(payload: AppSettings) -> AppSettings:
    repository.set_setting("generation_model", payload.generation_model.strip() or DEFAULT_GENERATION_MODEL)
    repository.set_setting("embedding_model", payload.embedding_model.strip() or DEFAULT_EMBEDDING_MODEL)
    return get_settings()


@app.get("/health/local-ai", response_model=LocalAiHealth)
def local_ai_health() -> LocalAiHealth:
    return local_ai.health()


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
    return repository.list_projects()


@app.patch("/projects/{project_id}", response_model=Project)
def update_project(project_id: int, payload: ProjectUpdate) -> Project:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="작품 제목을 입력해 주세요.")
    try:
        return repository.update_project_title(project_id, title)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="작품을 찾을 수 없습니다.") from error


@app.delete("/projects/{project_id}", response_model=ProjectDeleteResult)
def delete_project(project_id: int) -> ProjectDeleteResult:
    try:
        deleted_project_id = repository.delete_project(project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="작품을 찾을 수 없습니다.") from error
    try:
        RagService(chroma_path()).delete_project_index(project_id)
    except Exception:
        pass
    return ProjectDeleteResult(project_id=deleted_project_id)


@app.post("/documents/import", response_model=StoryDocument)
async def import_document(payload: DocumentImport) -> StoryDocument:
    path = Path(payload.path)
    try:
        content, file_format, content_hash = read_document(path)
    except UnsupportedDocumentFormat as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.") from error

    existing_documents = repository.list_documents(payload.project_id)
    # Re-importing the same file must be idempotent.  Without this guard a
    # second file-picker attempt created a duplicate chapter and shifted every
    # subsequent display number by one.
    duplicate = next((document for document in existing_documents if document.content_hash == content_hash), None)
    if duplicate is not None:
        return duplicate

    # Preserve the author's episode numbers from common filenames such as
    # ``episode-08.txt`` or ``8화.md``.  The old implementation used import
    # order, so selecting episode 08 first displayed it as 1화.
    filename = path.stem
    matches = re.findall(r"(?:^|[^0-9])(\d+)(?:[^0-9]|$)", filename)
    parsed_episode = int(matches[-1]) if matches else None
    if parsed_episode is not None and parsed_episode > 0:
        next_chapter_index = parsed_episode - 1
        occupied = next((document for document in existing_documents if document.chapter_index == next_chapter_index), None)
        if occupied is not None:
            raise HTTPException(
                status_code=409,
                detail=f"{parsed_episode}화 번호가 이미 사용 중입니다. 기존 회차를 교체하거나 파일명을 확인해 주세요.",
            )
    else:
        next_chapter_index = (
            max((document.chapter_index for document in existing_documents), default=-1) + 1
        )
    document = repository.add_document(
        project_id=payload.project_id,
        path=path,
        title=path.stem,
        file_format=file_format,
        content_hash=content_hash,
        content=content,
        chapter_index=next_chapter_index,
        preserve_analysis=True,
    )
    settings = get_settings()
    request_rag = RagService(chroma_path(), embedding_model=settings.embedding_model, repository=repository)
    rag_chunks = request_rag.split_text(content, document.id, payload.project_id)
    chunks = [chunk.text for chunk in rag_chunks] or split_chunks(content)
    repository.replace_chunks(payload.project_id, document.id, chunks)
    # Keep the last published graph visible while the new chapter is indexed
    # and reviewed. The next successful analysis transaction replaces derived
    # results atomically; importing a draft must not make the workspace look
    # empty or discard the author's previous decisions.
    if chunks:
        schedule_project_index(payload.project_id, settings.embedding_model)
    return document


@app.put("/documents/{document_id}", response_model=StoryDocument)
async def replace_document(document_id: int, payload: DocumentReplace) -> StoryDocument:
    try:
        document_path: Path
        if payload.content is not None:
            with repository.database.connect() as connection:
                existing = connection.execute("SELECT path, format, project_id FROM documents WHERE id=?", (document_id,)).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="원고를 찾을 수 없습니다.")
            content = payload.content
            file_format = existing["format"]
            document_path = Path(existing["path"])
            import hashlib
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        elif payload.path:
            content, file_format, content_hash = read_document(Path(payload.path))
            document_path = Path(payload.path)
        else:
            raise HTTPException(status_code=400, detail="수정할 원문 또는 파일이 필요합니다.")
        if not content.strip():
            raise HTTPException(status_code=400, detail="빈 원고로 교체할 수 없습니다.")
        rag = RagService(chroma_path(), embedding_model=get_settings().embedding_model, repository=repository)
        # Preserve the owning project on rebuilt chunks.  Passing a sentinel
        # project id here makes the replaced document invisible to
        # list_chunks(project_id) and therefore to retrieval/incremental
        # analysis after an author edits an existing episode.
        with repository.database.connect() as connection:
            row = connection.execute("SELECT project_id FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="원고를 찾을 수 없습니다.")
        project_id = int(row["project_id"])
        chunks = [chunk.text for chunk in rag.split_text(content, document_id, project_id)]
        document = repository.replace_document(document_id, document_path, file_format, content_hash, content, chunks)
    except (FileNotFoundError, KeyError) as error:
        raise HTTPException(status_code=404, detail="원고 또는 파일을 찾을 수 없습니다.") from error
    except UnsupportedDocumentFormat as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    schedule_project_index(document.project_id, get_settings().embedding_model)
    # Retrieval synchronizes the derived index before serving any results.
    return document


@app.get("/projects/{project_id}/review-history")
def review_history(project_id: int):
    return repository.review_history(project_id)


@app.get("/projects/{project_id}/documents", response_model=list[StoryDocument])
def list_documents(project_id: int) -> list[StoryDocument]:
    return repository.list_documents(project_id)


@app.get("/projects/{project_id}/settings", response_model=list[StorySetting])
def list_story_settings(project_id: int) -> list[StorySetting]:
    return repository.list_story_settings(project_id)


@app.post("/projects/{project_id}/settings", response_model=StorySetting)
def create_story_setting(project_id: int, payload: StorySettingCreate) -> StorySetting:
    try:
        return repository.add_story_setting(project_id, payload.title, payload.content, payload.certainty)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="작품을 찾을 수 없습니다.") from error


@app.patch("/settings/{setting_id}", response_model=StorySetting)
def update_story_setting(setting_id: int, payload: StorySettingUpdate) -> StorySetting:
    try:
        return repository.update_story_setting(setting_id, payload.title, payload.content, payload.certainty)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="설정 메모를 찾을 수 없습니다.") from error


@app.delete("/settings/{setting_id}", response_model=dict[str, int])
def delete_story_setting(setting_id: int) -> dict[str, int]:
    try:
        project_id = repository.delete_story_setting(setting_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="설정 메모를 찾을 수 없습니다.") from error
    return {"project_id": project_id}


@app.get("/projects/{project_id}/foreshadowing/status", response_model=list[ForeshadowingStatus])
def list_foreshadowing_statuses(project_id: int) -> list[ForeshadowingStatus]:
    return repository.list_foreshadowing_statuses(project_id)


@app.patch("/projects/{project_id}/foreshadowing/{entity_id}", response_model=ForeshadowingStatus)
def set_foreshadowing_status(project_id: int, entity_id: int, payload: ForeshadowingStatusUpdate) -> ForeshadowingStatus:
    try:
        return repository.set_foreshadowing_status(project_id, entity_id, payload.status)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="떡밥 후보를 찾을 수 없습니다.") from error


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
        RagService(chroma_path(), embedding_model=settings.embedding_model, repository=repository),
        LocalLlmExtractor(model=settings.generation_model, model_dir=models_path()),
    )
    try:
        result = analyzer.analyze_project(project_id)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "entity_count": result.entity_count,
        "relation_count": result.relation_count,
        "issue_count": result.issue_count,
    }


@app.post("/projects/{project_id}/analyze/gpt")
def analyze_project_gpt(project_id: int, payload: ManuscriptAnalysisRequest):
    if not payload.consent:
        raise HTTPException(status_code=400, detail="원문 전송 동의가 필요합니다.")
    settings = get_settings()
    analyzer = GptStoryAnalyzer(repository,
        RagService(chroma_path(), embedding_model=settings.embedding_model, repository=repository), chatgpt_connection)
    try:
        return analyzer.analyze(project_id, payload.model, payload.effort, force=payload.force,
                                batch_limit=payload.batch_limit,
                                start_chapter=payload.start_chapter, end_chapter=payload.end_chapter)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/projects/{project_id}/analysis/status", response_model=AnalysisJob)
def analysis_status(project_id: int) -> AnalysisJob:
    job = repository.latest_analysis_job(project_id)
    if job is not None:
        return job
    return AnalysisJob(
        id=0,
        project_id=project_id,
        status=AnalysisStatus.idle,
        current_step="idle",
        progress=0,
        message="분석 대기 중입니다.",
        created_at="",
        updated_at="",
    )


@app.get("/projects/{project_id}/analysis/estimate")
def analysis_estimate(
    project_id: int,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
) -> dict[str, int | None]:
    """Estimate bounded GPT work using the same chunks as the analyzer.

    Chapter bounds are zero-based, matching the graph endpoint and GPT
    analysis request. Invalid ranges are rejected before any work is queued.
    """
    if start_chapter is not None and end_chapter is not None and start_chapter > end_chapter:
        raise HTTPException(status_code=422, detail="분석 회차 범위가 올바르지 않습니다.")
    documents = repository.list_documents(project_id)
    if start_chapter is not None or end_chapter is not None:
        documents = [document for document in documents if
                     (start_chapter is None or document.chapter_index >= start_chapter) and
                     (end_chapter is None or document.chapter_index <= end_chapter)]
    document_ids = {document.id for document in documents}
    rows = [row for row in repository.list_chunks(project_id) if row["document_id"] in document_ids]
    return {
        "document_count": len(documents),
        # Report the canonical manuscript size. Chunk overlap is useful for
        # retrieval but must not inflate the amount of source text shown to
        # the writer or used in workload estimates.
        "manuscript_chars": sum(len(document.content) for document in documents),
        "chunk_count": len(rows),
        "review_window_count": count_review_windows(documents, rows),
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
    }


def recommend_analysis_plan(review_windows: int) -> tuple[str, int, str]:
    if review_windows <= 20:
        return "full", review_windows or 1, "전체 범위를 한 번에 검토해도 되는 규모입니다."
    if review_windows <= 100:
        return "segmented", 20, "회차 묶음으로 나누어 검토하면 진행 상황과 재시도를 관리하기 쉽습니다."
    return "staged", 20, "장편 규모입니다. 20개 구간씩 단계적으로 검토하고 완료분을 먼저 확인하세요."


def analysis_batch_count(review_windows: int, batch_size: int) -> int:
    if review_windows <= 0:
        return 0
    return (review_windows + batch_size - 1) // batch_size


@app.get("/projects/{project_id}/analysis/plan")
def analysis_plan(
    project_id: int,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
) -> dict[str, int | str | None]:
    """Recommend a safe review mode from the measured workload."""
    estimate = analysis_estimate(project_id, start_chapter, end_chapter)
    windows = int(estimate["review_window_count"])
    mode, batch_size, message = recommend_analysis_plan(windows)
    # Measured local-throughput hints: EmbeddingGemma ~7 chunks/s and Qwen
    # llama.cpp ~1.4 chunks/s on the validation laptop. Keep this explicitly
    # approximate; the progress panel remains authoritative once indexing starts.
    chunks = int(estimate["chunk_count"])
    embedding_model = get_settings().embedding_model
    chunks_per_second = 7.0 if embedding_model == "embeddinggemma-300m" else 1.4
    embedding_memory_mb = 1659 if embedding_model == "embeddinggemma-300m" else 2275
    embedding_seconds = int(round(chunks / chunks_per_second)) if chunks else 0
    # Provider/network latency varies; this middle projection is guidance
    # only. Live job progress remains authoritative.
    gpt_seconds = windows * 30
    gpt_min_seconds = windows * 15
    gpt_max_seconds = windows * 60
    return {**estimate, "mode": mode, "recommended_batch_size": batch_size,
            "embedding_model": embedding_model,
            "embedding_estimate_seconds": embedding_seconds,
            "embedding_memory_estimate_mb": embedding_memory_mb,
            "gpt_estimate_seconds": gpt_seconds,
            "gpt_estimate_min_seconds": gpt_min_seconds,
            "gpt_estimate_max_seconds": gpt_max_seconds,
            "batch_count": analysis_batch_count(windows, batch_size), "message": message}


@app.post("/projects/{project_id}/analysis/cancel", response_model=AnalysisJob)
def cancel_analysis(project_id: int) -> AnalysisJob:
    job = repository.latest_analysis_job(project_id)
    if job and job.status != AnalysisStatus.running:
        return job
    return repository.cancel_analysis(project_id, preserve_results=bool(job and job.current_step.startswith("gpt_")))


@app.get("/projects/{project_id}/graph", response_model=GraphPayload)
def project_graph(
    project_id: int,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
) -> GraphPayload:
    return repository.graph(project_id, start_chapter=start_chapter, end_chapter=end_chapter)


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


@app.get("/relations/{relation_id}/evidence", response_model=list[EvidenceChunk])
def relation_evidence(relation_id: int) -> list[EvidenceChunk]:
    import json
    with repository.database.connect() as connection:
        row = connection.execute("SELECT project_id,evidence_chunk_ids FROM relations WHERE id=?", (relation_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="관계를 찾을 수 없습니다.")
    return [EvidenceChunk(**chunk) for chunk in repository.get_chunks(json.loads(row['evidence_chunk_ids']))
            if chunk['project_id'] == row['project_id']]


def main() -> None:
    import uvicorn

    start_parent_process_monitor()
    repository.mark_running_jobs_interrupted()
    port = int(os.getenv("STORY_GUARD_BACKEND_PORT", "8765"))
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
