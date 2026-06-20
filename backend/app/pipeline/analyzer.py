from __future__ import annotations

import re
from dataclasses import dataclass

from typing_extensions import TypedDict

from backend.app.models import AnalysisStatus
from backend.app.repository import StoryRepository
from backend.app.services.local_llm import LocalLlmExtractor
from backend.app.services.rag import RagService


ENTITY_PATTERNS = {
    "character": re.compile(r"(?:인물|등장인물|캐릭터)\s*[:：]\s*([^\n]+)"),
    "place": re.compile(r"(?:장소|지역)\s*[:：]\s*([^\n]+)"),
    "organization": re.compile(r"(?:조직|세력)\s*[:：]\s*([^\n]+)"),
    "item": re.compile(r"(?:아이템|물건|유물)\s*[:：]\s*([^\n]+)"),
    "rule": re.compile(r"(?:규칙|설정)\s*[:：]\s*([^\n]+)"),
    "foreshadowing": re.compile(r"(?:떡밥|복선)\s*[:：]\s*([^\n]+)"),
}

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

CONTRADICTION_PATTERNS = [
    re.compile(r"(.{0,40})(모순|충돌|앞에서는|하지만 후반|설정 붕괴)(.{0,60})"),
    re.compile(r"(.{0,40})(죽었|사망).{0,40}(다시 등장|살아)(.{0,40})"),
    re.compile(r"(.{0,40})(모른다|처음 본다).{0,40}(이미 알고|전에 만난)(.{0,40})"),
]


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
        job = self.repository.create_job(project_id, AnalysisStatus.running, "분석 중")
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
            return self._analyze_with_heuristics(project_id)

        def parse(state: AnalysisState) -> AnalysisState:
            return state

        def extract_entities(state: AnalysisState) -> AnalysisState:
            state["result"] = self._analyze_with_heuristics(state["project_id"])
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

    def _analyze_with_heuristics(self, project_id: int) -> AnalysisResult:
        documents = self.repository.list_documents(project_id)
        chunks = self.repository.list_chunks(project_id)
        self.repository.clear_analysis(project_id)

        llm_result = self._try_llm_extraction(project_id, documents, chunks)
        if llm_result is not None:
            return llm_result

        entity_count = 0
        issue_count = 0
        seen_entities: dict[tuple[str, str], int] = {}

        for document in documents:
            for entity in self._extract_explicit_entities(project_id, document):
                seen_entities[(entity.type, entity.name)] = entity.id
                entity_count += 1

        self._add_cooccurrence_relations(project_id, chunks)
        issue_count += self._add_pattern_issues(project_id, chunks)
        issue_count += self._add_narrative_flow_issues(project_id)

        graph = self.repository.graph(project_id)
        return AnalysisResult(
            entity_count=len(graph.entities),
            relation_count=len(graph.relations),
            issue_count=len(graph.issues),
        )

    def _try_llm_extraction(self, project_id: int, documents: list, chunks: list[dict]) -> AnalysisResult | None:
        if not self.llm.enabled() or not documents:
            return None
        try:
            payload = self.llm.extract_story_facts("\n\n".join(document.content for document in documents))
        except Exception:
            return None

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

        for document in documents:
            for entity in self._extract_explicit_entities(project_id, document):
                entities_by_name.setdefault(entity.name, entity.id)

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
                evidence_chunk_ids=[chunks[0]["id"]] if chunks else [],
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
                evidence_chunk_ids=[chunks[0]["id"]] if chunks else [],
            )

        self._add_pattern_issues(project_id, chunks)
        self._add_cooccurrence_relations(project_id, chunks)
        self._add_narrative_flow_issues(project_id)

        graph = self.repository.graph(project_id)
        if not graph.entities and not graph.issues:
            return None
        return AnalysisResult(
            entity_count=len(graph.entities),
            relation_count=len(graph.relations),
            issue_count=len(graph.issues),
        )

    def _attach_retrieved_evidence(self, project_id: int) -> None:
        graph = self.repository.graph(project_id)
        for issue in graph.issues:
            retrieved: list[dict] = []
            if self.rag is not None:
                try:
                    retrieved = self.rag.retrieve(project_id, issue.description)
                except Exception:
                    retrieved = []
            if not retrieved:
                retrieved = self.repository.search_chunks_lexical(project_id, issue.description)
            chunk_ids = [int(chunk["chunk_id"] if "chunk_id" in chunk else chunk["id"]) for chunk in retrieved]
            if chunk_ids:
                self.repository.update_issue_evidence(issue.id, chunk_ids)

    def _extract_explicit_entities(self, project_id: int, document) -> list:
        entities = []
        for entity_type, pattern in ENTITY_PATTERNS.items():
            for match in pattern.finditer(document.content):
                for raw_name in re.split(r"[,/、，]", match.group(1)):
                    name = raw_name.strip()
                    if not name:
                        continue
                    entities.append(
                        self.repository.upsert_entity(
                            project_id=project_id,
                            entity_type=entity_type,
                            name=name[:80],
                            aliases=[],
                            summary=f"{document.title}에서 추출된 {entity_type} 설정",
                            first_seen_document_id=document.id,
                        )
                    )
        return entities

    def _add_pattern_issues(self, project_id: int, chunks: list[dict]) -> int:
        graph = self.repository.graph(project_id)
        existing_text = "\n".join(f"{issue.title}\n{issue.description}" for issue in graph.issues)
        added = 0
        for chunk in chunks:
            for pattern in CONTRADICTION_PATTERNS:
                match = pattern.search(chunk["text"])
                if not match:
                    continue
                excerpt = " ".join(part.strip() for part in match.groups() if part.strip())
                description = excerpt or "원고에서 설정 충돌을 암시하는 표현을 발견했습니다."
                if excerpt and excerpt[:24] in existing_text:
                    break
                self.repository.add_issue(
                    project_id=project_id,
                    severity="high",
                    category="contradiction",
                    title="설정 충돌 후보",
                    description=description,
                    evidence_chunk_ids=[chunk["id"]],
                )
                existing_text += f"\n{description}"
                added += 1
                break
        return added

    def _add_narrative_flow_issues(self, project_id: int) -> int:
        documents = self.repository.list_documents(project_id)
        if len(documents) < 3:
            return 0
        graph = self.repository.graph(project_id)
        existing_text = "\n".join(f"{issue.title}\n{issue.description}" for issue in graph.issues)
        added = 0
        for entity in graph.entities:
            evidence_chunks = self.repository.search_chunks_lexical(project_id, entity.name, limit=3)
            evidence_chunk_ids = [int(chunk["id"]) for chunk in evidence_chunks]
            if (
                entity.appearance_state == "new"
                and entity.type in {"place", "organization", "item", "rule", "foreshadowing"}
                and entity.name not in existing_text
            ):
                category = "world_rule" if entity.type in {"place", "rule"} else "unresolved_foreshadowing"
                self.repository.add_issue(
                    project_id=project_id,
                    severity="medium",
                    category=category,
                    title="후반부 갑작스런 설정 등장",
                    description=(
                        f"{entity.name}은(는) {len(documents)}편 중 마지막 편에서 처음 언급됩니다. "
                        "후반 핵심 설정으로 쓰려면 앞부분의 암시나 도입 근거가 필요합니다."
                    ),
                    evidence_chunk_ids=evidence_chunk_ids,
                )
                existing_text += f"\n{entity.name}"
                added += 1
                continue
            if (
                entity.appearance_state == "dormant"
                and entity.type in {"character", "organization", "item", "foreshadowing"}
                and entity.document_count > 0
                and entity.name not in existing_text
            ):
                category = "relationship" if entity.type in {"character", "organization"} else "unresolved_foreshadowing"
                self.repository.add_issue(
                    project_id=project_id,
                    severity="low",
                    category=category,
                    title="언급이 끊긴 설정 후보",
                    description=(
                        f"{entity.name}은(는) 앞부분에서 {entity.mention_count}회 언급됐지만 "
                        "최근 편에서는 등장하지 않습니다. 기존 관계나 떡밥이 의도적으로 사라진 것인지 확인이 필요합니다."
                    ),
                    evidence_chunk_ids=evidence_chunk_ids,
                )
                existing_text += f"\n{entity.name}"
                added += 1
        return added

    def _add_cooccurrence_relations(self, project_id: int, chunks: list[dict]) -> int:
        graph = self.repository.graph(project_id)
        existing_pairs = {
            (relation.source_entity_id, relation.target_entity_id, relation.type)
            for relation in graph.relations
        }
        added = 0
        for chunk in chunks:
            text = chunk["text"]
            mentioned = [entity for entity in graph.entities if entity.name and entity.name in text]
            if len(mentioned) < 2:
                continue
            characters = [entity for entity in mentioned if entity.type == "character"]
            sources = characters or mentioned[:1]
            for source in sources:
                for target in mentioned:
                    if source.id == target.id:
                        continue
                    context = self._pair_context(source, target, text)
                    if not context:
                        continue
                    relation_type, confidence = self._classify_relation_context(source, target, context)
                    pair = (source.id, target.id, relation_type)
                    if pair in existing_pairs:
                        continue
                    self.repository.add_relation(
                        project_id=project_id,
                        source_entity_id=source.id,
                        target_entity_id=target.id,
                        relation_type=relation_type,
                        confidence=confidence,
                        evidence_chunk_ids=[chunk["id"]],
                    )
                    existing_pairs.add(pair)
                    added += 1
        return added

    def _pair_context(self, source, target, text: str) -> str:
        contexts = []
        for sentence in _split_sentences(text):
            stripped = sentence.strip()
            if not stripped or _is_metadata_sentence(stripped):
                continue
            if source.name in stripped and target.name in stripped:
                contexts.append(stripped)
        return " ".join(contexts[:2])

    def _classify_relation_context(self, source, target, text: str) -> tuple[str, float]:
        hostile_terms = (
            "적대",
            "대립",
            "의심",
            "배신",
            "공격",
            "습격",
            "위협",
            "추적",
            "살해",
            "죽이",
            "총",
            "방아쇠",
            "분노",
        )
        ally_terms = ("친구", "동료", "함께", "동행", "구했", "보호", "믿고", "믿었다", "협력")
        item_terms = ("들고", "쥐고", "묶여", "훔쳤", "발견", "주머니", "넘기면", "사용")
        organization_terms = ("소속", "대표", "조직", "회의", "사람", "후원회", "치안국")
        secret_terms = ("몰래", "거래", "비밀", "밀명", "숨겼", "감췄")
        clue_terms = ("조사", "기록", "보고", "확인", "단서", "지도", "문서", "수첩")

        if any(term in text for term in hostile_terms) and target.type in {
            "character",
            "organization",
        }:
            return "적대/의심", 0.86
        if any(term in text for term in ally_terms) and target.type == "character":
            return "동행/협력", 0.78
        if target.type == "item" and any(term in text for term in item_terms):
            return "소유/사용", 0.74
        if target.type == "organization" and any(term in text for term in organization_terms):
            return "소속/조직", 0.7
        if any(term in text for term in secret_terms) and target.type in {"character", "organization"}:
            return "비밀/거래", 0.66
        if any(term in text for term in clue_terms):
            return "정보/단서", 0.64
        if target.type == "place":
            return "등장 장소", 0.62
        if target.type == "rule":
            return "규칙 관련", 0.58
        if target.type == "foreshadowing":
            return "떡밥 관련", 0.56
        return "co_occurs", 0.34


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if part.strip()]


def _is_metadata_sentence(text: str) -> bool:
    return bool(re.match(r"^(인물|등장인물|캐릭터|장소|지역|조직|세력|아이템|물건|유물|규칙|설정|떡밥|복선)\s*[:：]", text))
