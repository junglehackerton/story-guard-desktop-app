from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import TypedDict

from backend.app.models import AnalysisStatus
from backend.app.repository import StoryRepository
from backend.app.services.local_llm import LocalLlmExtractor
from backend.app.services.rag import RagService


ALLOWED_ENTITY_TYPES = {
    "character",
    "place",
    "organization",
    "item",
    "event",
    "rule",
    "foreshadowing",
}

ALLOWED_ISSUE_CATEGORIES = {
    "timeline",
    "character_state",
    "world_rule",
    "relationship",
    "unresolved_foreshadowing",
    "contradiction",
}

ALLOWED_SEVERITIES = {"low", "medium", "high"}


@dataclass
class AnalysisResult:
    entity_count: int
    relation_count: int
    issue_count: int


class AnalysisState(TypedDict):
    project_id: int
    result: AnalysisResult | None


class StoryAnalyzer:
    def __init__(
        self,
        repository: StoryRepository,
        rag: RagService | None = None,
        llm: LocalLlmExtractor | None = None,
    ) -> None:
        self.repository = repository
        self.rag = rag
        self.llm = llm or LocalLlmExtractor()

    def analyze_project(self, project_id: int) -> AnalysisResult:
        job = self.repository.create_job(project_id, AnalysisStatus.running, "로컬 LLM 분석 중")
        try:
            result = self._run_graph(project_id)
        except Exception as error:
            self.repository.update_job(job.id, AnalysisStatus.failed, str(error))
            raise
        self.repository.update_job(
            job.id,
            AnalysisStatus.completed,
            f"엔티티 {result.entity_count}개, 관계 {result.relation_count}개, 이슈 {result.issue_count}개",
        )
        return result

    def _run_graph(self, project_id: int) -> AnalysisResult:
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return self._analyze_with_llm(project_id)

        def parse(state: AnalysisState) -> AnalysisState:
            return state

        def extract_entities(state: AnalysisState) -> AnalysisState:
            state["result"] = self._analyze_with_llm(state["project_id"])
            return state

        def extract_relations(state: AnalysisState) -> AnalysisState:
            return state

        def detect_issues(state: AnalysisState) -> AnalysisState:
            return state

        def retrieve_evidence(state: AnalysisState) -> AnalysisState:
            self._attach_retrieved_evidence(state["project_id"])
            return state

        def persist(state: AnalysisState) -> AnalysisState:
            return state

        graph = StateGraph(AnalysisState)
        graph.add_node("parse", parse)
        graph.add_node("extract_entities", extract_entities)
        graph.add_node("extract_relations", extract_relations)
        graph.add_node("detect_issues", detect_issues)
        graph.add_node("retrieve_evidence", retrieve_evidence)
        graph.add_node("persist", persist)
        graph.set_entry_point("parse")
        graph.add_edge("parse", "extract_entities")
        graph.add_edge("extract_entities", "extract_relations")
        graph.add_edge("extract_relations", "detect_issues")
        graph.add_edge("detect_issues", "retrieve_evidence")
        graph.add_edge("retrieve_evidence", "persist")
        graph.add_edge("persist", END)
        final_state = graph.compile().invoke({"project_id": project_id, "result": None})
        return final_state["result"] or AnalysisResult(0, 0, 0)

    def _analyze_with_llm(self, project_id: int) -> AnalysisResult:
        documents = self.repository.list_documents(project_id)
        chunks = self.repository.list_chunks(project_id)
        if not documents:
            self.repository.clear_analysis(project_id)
            return AnalysisResult(0, 0, 0)
        if not self.llm.enabled():
            raise RuntimeError("로컬 LLM 모델이 준비되지 않았습니다. 환경 설정에서 모델 설치를 실행해 주세요.")

        payload = self.llm.extract_story_facts("\n\n".join(document.content for document in documents))
        self.repository.clear_analysis(project_id)
        self._persist_llm_payload(project_id, documents, chunks, payload)
        graph = self.repository.graph(project_id)
        if not graph.entities and not graph.issues:
            raise RuntimeError("로컬 LLM 분석 결과가 비어 있습니다.")
        return AnalysisResult(
            entity_count=len(graph.entities),
            relation_count=len(graph.relations),
            issue_count=len(graph.issues),
        )

    def _persist_llm_payload(self, project_id: int, documents: list, chunks: list[dict], payload: dict) -> None:
        entities_by_name: dict[str, int] = {}
        for raw_entity in payload.get("entities", []):
            if not isinstance(raw_entity, dict):
                continue
            name = str(raw_entity.get("name", "")).strip()
            entity_type = str(raw_entity.get("type", "")).strip()
            if not name or entity_type not in ALLOWED_ENTITY_TYPES:
                continue
            aliases = raw_entity.get("aliases", [])
            entity = self.repository.upsert_entity(
                project_id=project_id,
                entity_type=entity_type,
                name=name[:80],
                aliases=[str(alias) for alias in aliases if str(alias).strip()] if isinstance(aliases, list) else [],
                summary=str(raw_entity.get("summary", ""))[:400],
                first_seen_document_id=documents[0].id,
            )
            entities_by_name[name] = entity.id
            for alias in entity.aliases:
                entities_by_name.setdefault(alias, entity.id)

        default_evidence = [chunks[0]["id"]] if chunks else []
        for raw_relation in payload.get("relations", []):
            if not isinstance(raw_relation, dict):
                continue
            source_id = entities_by_name.get(str(raw_relation.get("source", "")).strip())
            target_id = entities_by_name.get(str(raw_relation.get("target", "")).strip())
            if not source_id or not target_id or source_id == target_id:
                continue
            self.repository.add_relation(
                project_id=project_id,
                source_entity_id=source_id,
                target_entity_id=target_id,
                relation_type=str(raw_relation.get("type", "related_to"))[:80],
                confidence=float(raw_relation.get("confidence", 0.7) or 0.7),
                evidence_chunk_ids=default_evidence,
            )

        for raw_issue in payload.get("issues", []):
            if not isinstance(raw_issue, dict):
                continue
            severity = str(raw_issue.get("severity", "medium"))
            category = str(raw_issue.get("category", "contradiction"))
            self.repository.add_issue(
                project_id=project_id,
                severity=severity if severity in ALLOWED_SEVERITIES else "medium",
                category=category if category in ALLOWED_ISSUE_CATEGORIES else "contradiction",
                title=str(raw_issue.get("title", "설정 점검 후보"))[:120],
                description=str(raw_issue.get("description", ""))[:1000],
                evidence_chunk_ids=default_evidence,
            )

    def _attach_retrieved_evidence(self, project_id: int) -> None:
        if self.rag is None:
            return
        graph = self.repository.graph(project_id)
        for issue in graph.issues:
            try:
                retrieved = self.rag.retrieve(project_id, issue.description)
            except Exception:
                retrieved = []
            chunk_ids = [int(chunk["chunk_id"] if "chunk_id" in chunk else chunk["id"]) for chunk in retrieved]
            if chunk_ids:
                self.repository.update_issue_evidence(issue.id, chunk_ids)
