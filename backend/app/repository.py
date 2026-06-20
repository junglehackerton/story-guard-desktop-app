from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.database import Database, decode_json, encode_json
from backend.app.models import (
    AnalysisJob,
    AnalysisStatus,
    ContinuityIssue,
    EntityNode,
    GraphPayload,
    Project,
    RelationEdge,
    StoryDocument,
)


class StoryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_project(self, title: str, root_path: str | None = None) -> Project:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO projects (title, root_path) VALUES (?, ?)",
                (title, root_path),
            )
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return Project(**dict(row))

    def list_projects(self) -> list[Project]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [Project(**dict(row)) for row in rows]

    def update_project_title(self, project_id: int, title: str) -> Project:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE projects
                SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, project_id),
            )
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        return Project(**dict(row))

    def add_document(
        self,
        project_id: int,
        path: Path,
        title: str,
        file_format: str,
        content_hash: str,
        content: str,
        chapter_index: int = 0,
    ) -> StoryDocument:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO documents
                  (project_id, path, title, format, chapter_index, content_hash, content)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    str(path),
                    title,
                    file_format,
                    chapter_index,
                    content_hash,
                    content,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (project_id,),
            )
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return StoryDocument(**dict(row))

    def list_documents(self, project_id: int) -> list[StoryDocument]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE project_id = ? ORDER BY chapter_index, id",
                (project_id,),
            ).fetchall()
        return [StoryDocument(**dict(row)) for row in rows]

    def delete_document(self, document_id: int) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Document not found: {document_id}")
            project_id = int(row["project_id"])
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            connection.execute("DELETE FROM relations WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM issues WHERE project_id = ?", (project_id,))
            connection.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (project_id,),
            )
        return project_id

    def replace_chunks(self, project_id: int, document_id: int, chunks: list[str]) -> list[int]:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            ids: list[int] = []
            for index, text in enumerate(chunks):
                cursor = connection.execute(
                    """
                    INSERT INTO chunks (document_id, project_id, chunk_index, text)
                    VALUES (?, ?, ?, ?)
                    """,
                    (document_id, project_id, index, text),
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def list_chunks(self, project_id: int) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE project_id = ? ORDER BY document_id, chunk_index",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_chunks(self, chunk_ids: list[int]) -> list[dict]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM chunks WHERE id IN ({placeholders}) ORDER BY id",
                chunk_ids,
            ).fetchall()
        return [dict(row) for row in rows]

    def search_chunks_lexical(self, project_id: int, query: str, limit: int = 4) -> list[dict]:
        terms = [term for term in re_split_query(query) if len(term) >= 2]
        chunks = self.list_chunks(project_id)
        if not terms:
            return chunks[:limit]
        scored = []
        for chunk in chunks:
            text = chunk["text"]
            score = sum(text.count(term) for term in terms)
            if score:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:limit]]

    def clear_analysis(self, project_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM relations WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM issues WHERE project_id = ?", (project_id,))

    def upsert_entity(
        self,
        project_id: int,
        entity_type: str,
        name: str,
        aliases: list[str],
        summary: str,
        first_seen_document_id: int | None,
    ) -> EntityNode:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO entities
                  (project_id, type, name, aliases, summary, first_seen_document_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, type, name) DO UPDATE SET
                  aliases = excluded.aliases,
                  summary = excluded.summary,
                  first_seen_document_id = COALESCE(entities.first_seen_document_id, excluded.first_seen_document_id)
                """,
                (
                    project_id,
                    entity_type,
                    name,
                    encode_json(aliases),
                    summary,
                    first_seen_document_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM entities WHERE project_id = ? AND type = ? AND name = ?",
                (project_id, entity_type, name),
            ).fetchone()
        data = dict(row)
        data["aliases"] = decode_json(data["aliases"])
        return EntityNode(**data)

    def add_relation(
        self,
        project_id: int,
        source_entity_id: int,
        target_entity_id: int,
        relation_type: str,
        confidence: float,
        evidence_chunk_ids: list[int],
    ) -> RelationEdge:
        normalized_type = normalize_relation_type(relation_type)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO relations
                  (project_id, source_entity_id, target_entity_id, type, confidence, evidence_chunk_ids)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    source_entity_id,
                    target_entity_id,
                    normalized_type,
                    confidence,
                    encode_json(evidence_chunk_ids),
                ),
            )
            row = connection.execute(
                "SELECT * FROM relations WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        data = dict(row)
        data["evidence_chunk_ids"] = decode_json(data["evidence_chunk_ids"])
        return RelationEdge(**data)

    def add_issue(
        self,
        project_id: int,
        severity: str,
        category: str,
        title: str,
        description: str,
        evidence_chunk_ids: list[int],
    ) -> ContinuityIssue:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO issues
                  (project_id, severity, category, title, description, evidence_chunk_ids)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    severity,
                    category,
                    title,
                    description,
                    encode_json(evidence_chunk_ids),
                ),
            )
            row = connection.execute(
                "SELECT * FROM issues WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        data = dict(row)
        data["evidence_chunk_ids"] = decode_json(data["evidence_chunk_ids"])
        return ContinuityIssue(**data)

    def update_issue_status(self, issue_id: int, status: str) -> ContinuityIssue:
        with self.database.connect() as connection:
            connection.execute("UPDATE issues SET status = ? WHERE id = ?", (status, issue_id))
            row = connection.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            raise KeyError(f"Issue not found: {issue_id}")
        data = dict(row)
        data["evidence_chunk_ids"] = decode_json(data["evidence_chunk_ids"])
        return ContinuityIssue(**data)

    def update_issue_evidence(self, issue_id: int, evidence_chunk_ids: list[int]) -> ContinuityIssue:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE issues SET evidence_chunk_ids = ? WHERE id = ?",
                (encode_json(evidence_chunk_ids), issue_id),
            )
            row = connection.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            raise KeyError(f"Issue not found: {issue_id}")
        data = dict(row)
        data["evidence_chunk_ids"] = decode_json(data["evidence_chunk_ids"])
        return ContinuityIssue(**data)

    def graph(self, project_id: int) -> GraphPayload:
        with self.database.connect() as connection:
            entity_rows = connection.execute(
                "SELECT * FROM entities WHERE project_id = ? ORDER BY type, name",
                (project_id,),
            ).fetchall()
            relation_rows = connection.execute(
                "SELECT * FROM relations WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
            issue_rows = connection.execute(
                "SELECT * FROM issues WHERE project_id = ? ORDER BY id DESC",
                (project_id,),
            ).fetchall()
            document_rows = connection.execute(
                "SELECT id, content FROM documents WHERE project_id = ? ORDER BY chapter_index, id",
                (project_id,),
            ).fetchall()
        entities = []
        entity_payloads: list[dict[str, Any]] = []
        for row in entity_rows:
            data = dict(row)
            data["aliases"] = decode_json(data["aliases"])
            entity_payloads.append(data)
        entity_metrics = _entity_story_metrics(entity_payloads, [dict(row) for row in document_rows])
        for data in entity_payloads:
            data.update(entity_metrics.get(int(data["id"]), {}))
            entities.append(EntityNode(**data))
        relations = []
        for row in relation_rows:
            data = dict(row)
            data["evidence_chunk_ids"] = decode_json(data["evidence_chunk_ids"])
            data["type"] = normalize_relation_type(str(data["type"]))
            data.update(_relation_story_metrics(data, entity_metrics, len(document_rows)))
            relations.append(RelationEdge(**data))
        issues = []
        for row in issue_rows:
            data = dict(row)
            data["evidence_chunk_ids"] = decode_json(data["evidence_chunk_ids"])
            issues.append(ContinuityIssue(**data))
        return GraphPayload(entities=entities, relations=relations, issues=issues)

    def create_job(self, project_id: int, status: AnalysisStatus, message: str) -> AnalysisJob:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO analysis_jobs (project_id, status, message) VALUES (?, ?, ?)",
                (project_id, status.value, message),
            )
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return AnalysisJob(**dict(row))

    def update_job(self, job_id: int, status: AnalysisStatus, message: str) -> AnalysisJob:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, message, job_id),
            )
            row = connection.execute("SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        return AnalysisJob(**dict(row))

    def get_setting(self, key: str, default: str = "") -> str:
        with self.database.connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )


def re_split_query(query: str) -> list[str]:
    import re

    return [part.strip() for part in re.split(r"[\s,.;:!?()\[\]{}\"'“”‘’]+", query) if part.strip()]


def normalize_relation_type(relation_type: str) -> str:
    value = relation_type.strip()
    normalized = value.casefold()
    if not value:
        return "관련"
    if normalized in {"co_occurs", "co-occurs", "co occurs", "related_to", "related"}:
        return "co_occurs"
    if any(term in normalized for term in ("own", "has", "use", "possess")) or any(
        term in value for term in ("소유", "사용", "가지", "쥐고", "所有", "擁有", "拥有")
    ):
        return "소유/사용"
    if any(term in normalized for term in ("ally", "friend", "protect", "support", "companion")) or any(
        term in value for term in ("동맹", "친구", "보호", "협력", "同行")
    ):
        return "동행/협력"
    if any(term in normalized for term in ("enemy", "hostile", "conflict", "betray", "suspect", "rival")) or any(
        term in value for term in ("적대", "대립", "의심", "배신", "對立", "对立", "懷疑", "怀疑")
    ):
        return "적대/의심"
    if any(term in normalized for term in ("member", "belongs", "organization", "leader")) or any(
        term in value for term in ("소속", "조직", "대표", "所屬", "所属")
    ):
        return "소속/조직"
    if any(term in normalized for term in ("place", "located", "visit", "appear")) or any(
        term in value for term in ("장소", "등장", "방문", "위치")
    ):
        return "등장 장소"
    if "rule" in normalized or any(term in value for term in ("규칙", "세계", "설정")):
        return "규칙 관련"
    if any(term in normalized for term in ("foreshadow", "hint")) or any(
        term in value for term in ("떡밥", "복선")
    ):
        return "떡밥 관련"
    if any(term in normalized for term in ("secret", "deal", "trade")) or any(
        term in value for term in ("비밀", "거래", "밀명", "몰래")
    ):
        return "비밀/거래"
    if any(term in normalized for term in ("info", "clue", "investigate", "report")) or any(
        term in value for term in ("정보", "단서", "조사", "보고", "記錄", "情報")
    ):
        return "정보/단서"
    if any("\u4e00" <= char <= "\u9fff" for char in value):
        return "관련"
    return value[:24]


def _entity_story_metrics(
    entities: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    if not entities:
        return {}
    document_count = len(documents)
    document_order = {int(document["id"]): index for index, document in enumerate(documents)}
    latest_index = document_count - 1
    raw_metrics: dict[int, dict[str, Any]] = {}
    max_mentions = 1

    for entity in entities:
        entity_id = int(entity["id"])
        terms = _mention_terms(entity)
        per_document_counts: list[tuple[int, int]] = []
        for document in documents:
            count = _count_mentions(str(document["content"]), terms)
            if count > 0:
                per_document_counts.append((int(document["id"]), count))
        mentioned_document_ids = [document_id for document_id, _ in per_document_counts]
        total_mentions = sum(count for _, count in per_document_counts)
        max_mentions = max(max_mentions, total_mentions)
        raw_metrics[entity_id] = {
            "mention_count": total_mentions,
            "document_ids": mentioned_document_ids,
            "document_count": len(mentioned_document_ids),
            "last_seen_document_id": mentioned_document_ids[-1] if mentioned_document_ids else None,
            "_counts": per_document_counts,
        }

    metrics: dict[int, dict[str, Any]] = {}
    for entity in entities:
        entity_id = int(entity["id"])
        raw = raw_metrics[entity_id]
        mentioned_document_ids = raw["document_ids"]
        mention_count = int(raw["mention_count"])
        state = "dormant"
        if mentioned_document_ids:
            first_index = document_order.get(mentioned_document_ids[0], 0)
            last_index = document_order.get(mentioned_document_ids[-1], 0)
            latest_count = dict(raw["_counts"]).get(documents[-1]["id"], 0) if documents else 0
            prior_peak = max(
                (count for document_id, count in raw["_counts"] if document_order.get(document_id, 0) < latest_index),
                default=latest_count,
            )
            late_arrival_index = max(1, int(document_count * 0.6))
            if document_count >= 3 and first_index >= late_arrival_index:
                state = "new"
            elif document_count >= 2 and first_index == latest_index:
                state = "new"
            elif last_index < latest_index:
                state = "dormant" if latest_index - last_index >= 2 else "fading"
            elif document_count >= 3 and prior_peak >= 3 and latest_count <= max(1, int(prior_peak * 0.35)):
                state = "fading"
            else:
                state = "active"

        visual_weight = 0.28 + min(mention_count / max_mentions, 1) * 0.72
        if state == "new":
            visual_weight = max(visual_weight, 0.7)
        if state == "dormant":
            visual_weight = min(visual_weight, 0.46)

        metrics[entity_id] = {
            "mention_count": mention_count,
            "document_ids": mentioned_document_ids,
            "document_count": raw["document_count"],
            "last_seen_document_id": raw["last_seen_document_id"],
            "appearance_state": state,
            "visual_weight": round(visual_weight, 3),
        }
    return metrics


def _mention_terms(entity: dict[str, Any]) -> list[str]:
    terms = [str(entity.get("name", "")).strip()]
    terms.extend(str(alias).strip() for alias in entity.get("aliases", []) if str(alias).strip())
    seen: set[str] = set()
    unique_terms = []
    for term in terms:
        normalized = term.casefold()
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        unique_terms.append(term)
    return unique_terms


def _count_mentions(text: str, terms: list[str]) -> int:
    normalized_text = text.casefold()
    return sum(normalized_text.count(term.casefold()) for term in terms)


def _relation_story_metrics(
    relation: dict[str, Any],
    entity_metrics: dict[int, dict[str, Any]],
    document_count: int,
) -> dict[str, Any]:
    source_metrics = entity_metrics.get(int(relation["source_entity_id"]), {})
    target_metrics = entity_metrics.get(int(relation["target_entity_id"]), {})
    source_documents = set(source_metrics.get("document_ids", []))
    target_documents = set(target_metrics.get("document_ids", []))
    shared_document_count = len(source_documents & target_documents)
    document_overlap = shared_document_count / max(document_count, 1)
    confidence = float(relation.get("confidence") or 0.55)
    relation_type = str(relation.get("type", ""))
    is_weak = relation_type == "co_occurs" or confidence < 0.5
    strength = 0.18 + confidence * 0.62 + document_overlap * 0.2
    return {
        "strength": round(max(0.05, min(strength, 1)), 3),
        "is_weak": is_weak,
        "is_recent": source_metrics.get("appearance_state") != "dormant"
        and target_metrics.get("appearance_state") != "dormant",
        "display_label": "" if relation_type == "co_occurs" else relation_type,
    }
