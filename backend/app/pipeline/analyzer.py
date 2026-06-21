from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from typing_extensions import TypedDict

from backend.app.models import AnalysisStatus
from backend.app.pipeline.candidates import collect_story_candidates
from backend.app.repository import StoryRepository
from backend.app.services.local_llm import LocalLlmExtractor, sanitize_story_payload
from backend.app.services.parser import split_chunks
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
MAX_ANALYSIS_SEGMENT_CHARS = 2400
ANALYSIS_SEGMENT_OVERLAP_CHARS = 180
MAX_ANALYSIS_CONTEXT_CHARS = 1400
ANALYSIS_PROMPT_VERSION = "episode-facts-v4"


@dataclass
class AnalysisResult:
    entity_count: int
    relation_count: int
    issue_count: int


class AnalysisCancelled(RuntimeError):
    def __init__(self) -> None:
        super().__init__("분석이 취소되어 생성 중이던 내용이 삭제되었습니다.")


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
        job = self.repository.create_running_analysis_job(
            project_id,
            "분석 작업을 준비하고 있습니다.",
            current_step="prepare",
            progress=5,
        )
        try:
            result = self._run_graph(project_id, job.id)
            self._raise_if_cancelled(job.id, project_id)
        except Exception as error:
            if isinstance(error, AnalysisCancelled):
                self.repository.cancel_analysis(project_id)
                raise
            self.repository.update_job(
                job.id,
                AnalysisStatus.failed,
                str(error),
                current_step="failed",
                progress=100,
            )
            raise
        completed = self.repository.update_running_job(
            job.id,
            AnalysisStatus.completed,
            f"엔티티 {result.entity_count}개, 관계 {result.relation_count}개, 이슈 {result.issue_count}개",
            current_step="completed",
            progress=100,
        )
        if completed.status == AnalysisStatus.cancelled:
            self.repository.clear_analysis(project_id)
            raise AnalysisCancelled()
        return result

    def _run_graph(self, project_id: int, job_id: int) -> AnalysisResult:
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return self._analyze_with_llm(project_id, job_id)

        def parse(state: AnalysisState) -> AnalysisState:
            self._progress(job_id, "parse", 12, "원고와 청크를 불러오는 중입니다.")
            return state

        def collect_candidates(state: AnalysisState) -> AnalysisState:
            self._raise_if_cancelled(job_id, state["project_id"])
            self._progress(job_id, "candidates", 18, "원문에서 인물/장소/관계 후보를 수집하는 중입니다.")
            return state

        def classify_candidates(state: AnalysisState) -> AnalysisState:
            self._raise_if_cancelled(job_id, state["project_id"])
            self._progress(job_id, "classify", 22, "후보를 정규화하고 LLM 판정 범위를 좁히는 중입니다.")
            return state

        def extract_entities(state: AnalysisState) -> AnalysisState:
            state["result"] = self._analyze_with_llm(state["project_id"], job_id)
            return state

        def extract_relations(state: AnalysisState) -> AnalysisState:
            self._raise_if_cancelled(job_id, state["project_id"])
            self._progress(job_id, "relations", 76, "엔티티 간 관계를 정리하는 중입니다.")
            return state

        def detect_issues(state: AnalysisState) -> AnalysisState:
            self._raise_if_cancelled(job_id, state["project_id"])
            self._progress(job_id, "issues", 84, "설정 충돌 후보를 점검하는 중입니다.")
            return state

        def retrieve_evidence(state: AnalysisState) -> AnalysisState:
            self._raise_if_cancelled(job_id, state["project_id"])
            self._progress(job_id, "retrieve", 90, "RAG 근거 chunk를 검색 중입니다.")
            self._attach_retrieved_evidence(state["project_id"])
            self._raise_if_cancelled(job_id, state["project_id"])
            return state

        def persist(state: AnalysisState) -> AnalysisState:
            self._raise_if_cancelled(job_id, state["project_id"])
            self._progress(job_id, "persist", 96, "그래프와 리포트를 정리하는 중입니다.")
            return state

        graph = StateGraph(AnalysisState)
        graph.add_node("parse", parse)
        graph.add_node("collect_candidates", collect_candidates)
        graph.add_node("classify_candidates", classify_candidates)
        graph.add_node("extract_entities", extract_entities)
        graph.add_node("extract_relations", extract_relations)
        graph.add_node("detect_issues", detect_issues)
        graph.add_node("retrieve_evidence", retrieve_evidence)
        graph.add_node("persist", persist)
        graph.set_entry_point("parse")
        graph.add_edge("parse", "collect_candidates")
        graph.add_edge("collect_candidates", "classify_candidates")
        graph.add_edge("classify_candidates", "extract_entities")
        graph.add_edge("extract_entities", "extract_relations")
        graph.add_edge("extract_relations", "detect_issues")
        graph.add_edge("detect_issues", "retrieve_evidence")
        graph.add_edge("retrieve_evidence", "persist")
        graph.add_edge("persist", END)
        final_state = graph.compile().invoke({"project_id": project_id, "result": None})
        return final_state["result"] or AnalysisResult(0, 0, 0)

    def _analyze_with_llm(self, project_id: int, job_id: int) -> AnalysisResult:
        self._progress(job_id, "parse", 18, "등록된 원고를 분석 입력으로 묶는 중입니다.")
        documents = self.repository.list_documents(project_id)
        chunks = self.repository.list_chunks(project_id)
        if not documents:
            self.repository.clear_analysis(project_id)
            return AnalysisResult(0, 0, 0)

        if not self.llm.enabled():
            raise RuntimeError("로컬 LLM 모델이 준비되지 않았습니다. 환경 설정에서 모델 설치를 실행해 주세요.")

        self._raise_if_cancelled(job_id, project_id)
        model_name = str(getattr(self.llm, "model", "local-llm"))
        payload: dict[str, list[dict[str, Any]]] = {"entities": [], "relations": [], "issues": [], "claims": []}
        processed_units = 0
        total_units = sum(max(len(self._analysis_inputs([document])), 1) for document in documents)
        for document_index, document in enumerate(documents, start=1):
            cached_payload = self.repository.get_document_analysis_cache(
                document.id,
                document.content_hash,
                model_name=model_name,
                prompt_version=ANALYSIS_PROMPT_VERSION,
            )
            if cached_payload is not None:
                cached_payload = self._augment_with_story_candidates(
                    document.content,
                    cached_payload,
                    known_entity_names=self._entity_names(payload),
                )
                self.repository.replace_episode_analysis(
                    project_id,
                    document.id,
                    document.content_hash,
                    cached_payload,
                    model_name=model_name,
                    prompt_version=ANALYSIS_PROMPT_VERSION,
                )
                self._merge_payloads(payload, cached_payload, document.id)
                processed_units += max(len(self._analysis_inputs([document])), 1)
                continue

            document_payload: dict[str, list[dict[str, Any]]] = {"entities": [], "relations": [], "issues": [], "claims": []}
            analysis_inputs = self._analysis_inputs([document], document_index=document_index)
            for analysis_input in analysis_inputs:
                self._raise_if_cancelled(job_id, project_id)
                progress = 24 + int((processed_units / max(total_units, 1)) * 36)
                self._progress(
                    job_id,
                    "extract",
                    progress,
                    (
                        f"LLM이 {document_index}/{len(documents)}화 "
                        f"{analysis_input['segment_index']}/{analysis_input['segment_count']}구간을 분석 중입니다."
                    ),
                )
                candidate_payload = collect_story_candidates(analysis_input["text"])
                known_entity_names = self._known_names(
                    self._entity_names(payload),
                    self._entity_names(candidate_payload),
                )
                try:
                    segment_payload = self.llm.extract_story_facts(
                        analysis_input["text"],
                        context=self._analysis_context(payload),
                        known_entity_names=known_entity_names,
                    )
                except RuntimeError as error:
                    if not self._is_recoverable_llm_output_error(error):
                        raise
                    self._progress(
                        job_id,
                        "extract",
                        progress,
                        (
                            f"LLM 출력 형식이 불완전한 {document_index}/{len(documents)}화 "
                            f"{analysis_input['segment_index']}/{analysis_input['segment_count']}구간은 "
                            "원문 후보로 보정하고 계속합니다."
                        ),
                    )
                    segment_payload = {"entities": [], "relations": [], "issues": [], "claims": []}
                segment_payload = self._augment_with_story_candidates(
                    analysis_input["text"],
                    segment_payload,
                    known_entity_names=self._entity_names(payload),
                    candidate_payload=candidate_payload,
                )
                evidence_ids = self._chunk_ids_for_document(chunks, document.id)
                self._attach_segment_evidence(segment_payload, evidence_ids)
                self._merge_payloads(payload, segment_payload, document.id)
                self._merge_payloads(document_payload, segment_payload, document.id)
                processed_units += 1
            if document_payload["entities"] or document_payload["relations"] or document_payload["issues"]:
                self.repository.replace_episode_analysis(
                    project_id,
                    document.id,
                    document.content_hash,
                    document_payload,
                    model_name=model_name,
                    prompt_version=ANALYSIS_PROMPT_VERSION,
                )

        payload = sanitize_story_payload(
            self.repository.episode_payload(project_id),
            story_text="\n\n".join(str(document.content) for document in documents),
        )
        payload["issues"] = self._issues_from_claims(payload.get("claims", []))
        self._detect_continuity_issues(project_id, documents, payload, job_id)
        self._raise_if_cancelled(job_id, project_id)
        self._progress(job_id, "relations", 62, "LLM이 추출한 관계를 저장 가능한 형태로 정리하는 중입니다.")
        self.repository.clear_analysis(project_id)
        self._persist_llm_payload(project_id, documents, chunks, payload, job_id)
        self._raise_if_cancelled(job_id, project_id)
        self._progress(job_id, "validate", 72, "설정 충돌 후보와 빈 결과 여부를 검증 중입니다.")
        graph = self.repository.graph(project_id)
        if not graph.entities and not graph.issues:
            raise RuntimeError("로컬 LLM 분석 결과가 비어 있습니다.")
        return AnalysisResult(
            entity_count=len(graph.entities),
            relation_count=len(graph.relations),
            issue_count=len(graph.issues),
        )

    def _is_recoverable_llm_output_error(self, error: RuntimeError) -> bool:
        message = str(error)
        return (
            "분석 결과 형식" in message
            or "형식을 완성하지" in message
            or "JSON 응답" in message
        )

    def _augment_with_story_candidates(
        self,
        story_text: str,
        payload: dict,
        known_entity_names: list[str],
        candidate_payload: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        candidates = candidate_payload or collect_story_candidates(story_text)
        combined = {
            "entities": [
                *candidates.get("entities", []),
                *[entity for entity in payload.get("entities", []) if isinstance(entity, dict)],
            ],
            "relations": [
                *candidates.get("relations", []),
                *[relation for relation in payload.get("relations", []) if isinstance(relation, dict)],
            ],
            "issues": [issue for issue in payload.get("issues", []) if isinstance(issue, dict)],
        }
        if isinstance(payload.get("claims"), list):
            combined["claims"] = [claim for claim in payload["claims"] if isinstance(claim, dict)]
        return sanitize_story_payload(
            combined,
            known_entity_names=known_entity_names,
            story_text=story_text,
        )

    def _persist_llm_payload(
        self,
        project_id: int,
        documents: list,
        chunks: list[dict],
        payload: dict,
        job_id: int,
    ) -> None:
        entities_by_name: dict[str, int] = {}
        for raw_entity in payload.get("entities", []):
            self._raise_if_cancelled(job_id, project_id)
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
                first_seen_document_id=int(raw_entity.get("_first_seen_document_id") or documents[0].id),
            )
            entities_by_name[name] = entity.id
            for alias in entity.aliases:
                entities_by_name.setdefault(alias, entity.id)

        seen_relation_keys: set[tuple[int, int, str]] = set()
        for raw_relation in payload.get("relations", []):
            self._raise_if_cancelled(job_id, project_id)
            if not isinstance(raw_relation, dict):
                continue
            source_id = entities_by_name.get(str(raw_relation.get("source", "")).strip())
            target_id = entities_by_name.get(str(raw_relation.get("target", "")).strip())
            if not source_id or not target_id or source_id == target_id:
                continue
            relation_type = str(raw_relation.get("type", "related_to"))[:80]
            relation_key = (source_id, target_id, relation_type)
            if relation_key in seen_relation_keys:
                continue
            seen_relation_keys.add(relation_key)
            evidence_chunk_ids = self._payload_evidence_ids(raw_relation)
            if not evidence_chunk_ids:
                document_id = int(raw_relation.get("_document_id") or 0)
                evidence_chunk_ids = self._chunk_ids_for_document(chunks, document_id)[:2]
            if not evidence_chunk_ids and chunks:
                evidence_chunk_ids = [int(chunks[0]["id"])]
            self.repository.add_relation(
                project_id=project_id,
                source_entity_id=source_id,
                target_entity_id=target_id,
                relation_type=relation_type,
                confidence=float(raw_relation.get("confidence", 0.7) or 0.7),
                evidence_chunk_ids=evidence_chunk_ids,
            )

        for raw_issue in payload.get("issues", []):
            self._raise_if_cancelled(job_id, project_id)
            if not isinstance(raw_issue, dict):
                continue
            severity = str(raw_issue.get("severity", "medium"))
            category = str(raw_issue.get("category", "contradiction"))
            evidence_chunk_ids = self._payload_evidence_ids(raw_issue)
            if not evidence_chunk_ids and chunks:
                evidence_chunk_ids = [int(chunks[0]["id"])]
            self.repository.add_issue(
                project_id=project_id,
                severity=severity if severity in ALLOWED_SEVERITIES else "medium",
                category=category if category in ALLOWED_ISSUE_CATEGORIES else "contradiction",
                title=str(raw_issue.get("title", "설정 점검 후보"))[:120],
                description=str(raw_issue.get("description", ""))[:1000],
                evidence_chunk_ids=evidence_chunk_ids,
            )

    def _detect_continuity_issues(
        self,
        project_id: int,
        documents: list,
        payload: dict[str, list[dict[str, Any]]],
        job_id: int,
    ) -> None:
        detector = getattr(self.llm, "detect_continuity_issues", None)
        if not callable(detector):
            return
        self._raise_if_cancelled(job_id, project_id)
        self._progress(job_id, "issues", 66, "누적 회차 기준으로 설정 붕괴 후보를 점검 중입니다.")
        issues = detector(
            self._continuity_issue_text(documents),
            context=self._analysis_context(payload),
            known_entity_names=self._entity_names(payload),
        )
        self._merge_payloads(payload, {"entities": [], "relations": [], "issues": issues}, documents[-1].id)

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

    def _analysis_inputs(self, documents: list, document_index: int | None = None) -> list[dict[str, Any]]:
        analysis_inputs: list[dict[str, Any]] = []
        for fallback_index, document in enumerate(documents, start=1):
            current_document_index = document_index or fallback_index
            segments = split_chunks(
                document.content,
                max_chars=MAX_ANALYSIS_SEGMENT_CHARS,
                overlap=ANALYSIS_SEGMENT_OVERLAP_CHARS,
            )
            if not segments and document.content.strip():
                segments = [document.content.strip()[:MAX_ANALYSIS_SEGMENT_CHARS]]
            for segment_index, segment in enumerate(segments, start=1):
                title = str(getattr(document, "title", f"{document_index}화")).strip()
                text = segment.strip()
                analysis_inputs.append(
                    {
                        "document_id": document.id,
                        "document_index": current_document_index,
                        "segment_index": segment_index,
                        "segment_count": len(segments),
                        "text": text,
                    }
                )
        return analysis_inputs

    def _chunk_ids_for_document(self, chunks: list[dict], document_id: int) -> list[int]:
        return [
            int(chunk["id"])
            for chunk in chunks
            if int(chunk.get("document_id") or 0) == int(document_id)
        ]

    def _attach_segment_evidence(self, payload: dict[str, Any], evidence_chunk_ids: list[int]) -> None:
        if not evidence_chunk_ids:
            return
        for key in ("entities", "relations", "issues", "claims"):
            values = payload.get(key, [])
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, dict) and not value.get("evidence_chunk_ids"):
                    value["evidence_chunk_ids"] = evidence_chunk_ids[:2]

    def _payload_evidence_ids(self, payload: dict[str, Any]) -> list[int]:
        raw_ids = payload.get("evidence_chunk_ids", [])
        if not isinstance(raw_ids, list):
            return []
        evidence_ids: list[int] = []
        for raw_id in raw_ids:
            try:
                evidence_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        return list(dict.fromkeys(evidence_ids))

    def _issues_from_claims(self, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            title = str(claim.get("subject", "")).strip()
            description = str(claim.get("description", "")).strip()
            if not title and not description:
                continue
            key = (title, description)
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                {
                    "severity": str(claim.get("value", "medium")) or "medium",
                    "category": str(claim.get("type", "contradiction")) or "contradiction",
                    "title": title or "설정 점검 후보",
                    "description": description,
                    "evidence_chunk_ids": claim.get("evidence_chunk_ids", []),
                }
            )
        return issues

    def _merge_payloads(
        self,
        aggregate: dict[str, list[dict[str, Any]]],
        payload: dict,
        document_id: int,
    ) -> None:
        entity_index = {
            (str(entity.get("type", "")), str(entity.get("name", ""))): entity
            for entity in aggregate["entities"]
        }
        for raw_entity in payload.get("entities", []):
            if not isinstance(raw_entity, dict):
                continue
            entity_type = str(raw_entity.get("type", "")).strip()
            name = str(raw_entity.get("name", "")).strip()
            if not entity_type or not name:
                continue
            key = (entity_type, name)
            aliases = raw_entity.get("aliases", [])
            clean_aliases = [str(alias) for alias in aliases if str(alias).strip()] if isinstance(aliases, list) else []
            if key in entity_index:
                existing_aliases = entity_index[key].setdefault("aliases", [])
                if isinstance(existing_aliases, list):
                    for alias in clean_aliases:
                        if alias not in existing_aliases:
                            existing_aliases.append(alias)
                continue
            entity = dict(raw_entity)
            entity["type"] = entity_type
            entity["name"] = name
            entity["aliases"] = clean_aliases
            entity["_first_seen_document_id"] = document_id
            aggregate["entities"].append(entity)
            entity_index[key] = entity

        relation_keys = {
            (
                str(relation.get("source", "")),
                str(relation.get("target", "")),
                str(relation.get("type", "")),
            )
            for relation in aggregate["relations"]
        }
        for raw_relation in payload.get("relations", []):
            if not isinstance(raw_relation, dict):
                continue
            source = str(raw_relation.get("source", "")).strip()
            target = str(raw_relation.get("target", "")).strip()
            relation_type = str(raw_relation.get("type", "")).strip()
            if not source or not target or source == target or not relation_type:
                continue
            key = (source, target, relation_type)
            if key in relation_keys:
                continue
            aggregate["relations"].append(dict(raw_relation))
            relation_keys.add(key)

        issue_keys = {
            (str(issue.get("title", "")), str(issue.get("description", "")))
            for issue in aggregate["issues"]
        }
        for raw_issue in payload.get("issues", []):
            if not isinstance(raw_issue, dict):
                continue
            title = str(raw_issue.get("title", "")).strip()
            description = str(raw_issue.get("description", "")).strip()
            if not title and not description:
                continue
            key = (title, description)
            if key in issue_keys:
                continue
            aggregate["issues"].append(dict(raw_issue))
            issue_keys.add(key)

        claim_keys = {
            (
                str(claim.get("subject", "")),
                str(claim.get("type", "")),
                str(claim.get("description", "")),
            )
            for claim in aggregate.get("claims", [])
        }
        for raw_claim in payload.get("claims", []):
            if not isinstance(raw_claim, dict):
                continue
            subject = str(raw_claim.get("subject", "")).strip()
            claim_type = str(raw_claim.get("type", "")).strip()
            description = str(raw_claim.get("description", "")).strip()
            if not subject and not description:
                continue
            key = (subject, claim_type, description)
            if key in claim_keys:
                continue
            aggregate.setdefault("claims", []).append(dict(raw_claim))
            claim_keys.add(key)

    def _analysis_context(self, payload: dict[str, list[dict[str, Any]]]) -> str:
        lines: list[str] = []
        entity_parts = [
            f"{entity.get('type')}:{entity.get('name')}({entity.get('summary', '')})"
            for entity in payload.get("entities", [])[:30]
            if entity.get("name")
        ]
        if entity_parts:
            lines.append("기존 엔티티: " + "; ".join(entity_parts))
        relation_parts = [
            f"{relation.get('source')} -{relation.get('type')}- {relation.get('target')}"
            for relation in payload.get("relations", [])[:30]
            if relation.get("source") and relation.get("target")
        ]
        if relation_parts:
            lines.append("기존 관계: " + "; ".join(relation_parts))
        issue_parts = [
            str(issue.get("title", ""))
            for issue in payload.get("issues", [])[:10]
            if issue.get("title")
        ]
        if issue_parts:
            lines.append("기존 이슈 후보: " + "; ".join(issue_parts))
        return "\n".join(lines)[:MAX_ANALYSIS_CONTEXT_CHARS]

    def _continuity_issue_text(self, documents: list) -> str:
        selected_documents = documents if len(documents) <= 6 else [*documents[:2], *documents[-4:]]
        excerpts: list[str] = []
        for document in selected_documents:
            content = str(getattr(document, "content", "")).strip()
            excerpt = self._head_tail_excerpt(content, 520)
            title = str(getattr(document, "title", "")).strip() or "원고"
            excerpts.append(f"[{title}]\n{excerpt}")
        return "\n\n".join(excerpts)

    def _head_tail_excerpt(self, text: str, max_chars: int) -> str:
        clean_text = " ".join(text.split())
        if len(clean_text) <= max_chars:
            return clean_text
        half = max_chars // 2
        return f"{clean_text[:half]} ... {clean_text[-half:]}"

    def _entity_names(self, payload: dict[str, list[dict[str, Any]]]) -> list[str]:
        names: list[str] = []
        for entity in payload.get("entities", []):
            name = str(entity.get("name", "")).strip()
            if name and name not in names:
                names.append(name)
            aliases = entity.get("aliases", [])
            if isinstance(aliases, list):
                for alias in aliases:
                    alias_value = str(alias).strip()
                    if alias_value and alias_value not in names:
                        names.append(alias_value)
        return names

    def _known_names(self, *groups: list[str]) -> list[str]:
        names: list[str] = []
        for group in groups:
            for name in group:
                if name and name not in names:
                    names.append(name)
        return names

    def _progress(self, job_id: int, current_step: str, progress: int, message: str) -> None:
        job = self.repository.update_running_job(
            job_id,
            AnalysisStatus.running,
            message,
            current_step=current_step,
            progress=progress,
        )
        if job.status == AnalysisStatus.cancelled:
            raise AnalysisCancelled()

    def _raise_if_cancelled(self, job_id: int, project_id: int) -> None:
        job = self.repository.get_job(job_id)
        if job is not None and job.status == AnalysisStatus.cancelled:
            self.repository.clear_analysis(project_id)
            raise AnalysisCancelled()
