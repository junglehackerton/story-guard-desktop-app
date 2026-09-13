from __future__ import annotations

from contextlib import nullcontext

import json
from pathlib import Path
from typing import Any

from backend.app.database import Database, decode_json, encode_json
from backend.app.models import (
    AnalysisJob,
    AnalysisStatus,
    ContinuityIssue,
    EntityNode,
    GraphHealth,
    GraphRange,
    GraphPayload,
    Project,
    RelationChange,
    RelationTimelineEvent,
    RelationEdge,
    StoryDocument,
    StorySetting,
    ForeshadowingStatus,
)


def close_unfinished_windows(raw_details: str | None, message: str) -> str:
    """Close diagnostics only; validated responses and their checkpoints stay intact."""
    details = decode_json(raw_details)
    for window in details:
        for item in [window, *window.get('parts', [])]:
            if item.get('status') == 'running':
                item.update(status='interrupted', error=message)
            elif item.get('status') == 'queued':
                item.update(status='deferred')
    return encode_json(details)


def relation_types_conflict(types: set[str] | list[str] | tuple[str, ...]) -> bool:
    """Return a conservative conflict candidate for opposing predicates.

    This is intentionally lexical and review-oriented: chapter order,
    negation scope, and later exceptions remain the author's decision.
    """
    labels = [str(value).strip().casefold() for value in types]
    positive = any(
        any(term in value for term in (
            "동행", "협력", "동맹", "친구", "보호", "신뢰", "계약 체결", "소유함", "허용", "승인",
            "ally", "friend", "protect", "trust", "agreed", "owns", "allows",
        ))
        for value in labels
    )
    negative = any(
        any(term in value for term in (
            "적대", "대립", "배신", "의심", "충돌", "거절", "계약 해지", "계약 파기", "계약 거부",
            "계약 없이", "사용 불가", "금지", "소유하지", "enemy", "hostile", "betray", "suspect",
            "conflict", "refus", "reject", "forbidden", "without",
        ))
        for value in labels
    )
    return positive and negative


def _unambiguous_entity_term_index(entity_rows) -> tuple[dict[str, int], set[str]]:
    """Build a term index without guessing through colliding aliases.

    Short role labels are frequently shared by multiple entities.  Returning
    those terms in ``ambiguous`` lets timeline and change calculations skip
    them instead of attributing an event to whichever row happened to appear
    first.
    """
    index: dict[str, int] = {}
    ambiguous: set[str] = set()

    def register(raw_term: object, entity_id: int) -> None:
        term = str(raw_term).strip()
        if not term or term in ambiguous:
            return
        previous = index.get(term)
        if previous is None:
            index[term] = entity_id
        elif previous != entity_id:
            ambiguous.add(term)
            index.pop(term, None)

    for row in entity_rows:
        entity_id = int(row["id"])
        register(row["name"], entity_id)
        for alias in decode_json(row["aliases"]):
            register(alias, entity_id)
    return index, ambiguous


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
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM documents d WHERE d.project_id = p.id) AS document_count,
                       (SELECT COUNT(*) FROM documents d WHERE d.project_id = p.id AND NOT EXISTS (SELECT 1 FROM document_analysis_cache c WHERE c.document_id = d.id AND c.content_hash = d.content_hash)) AS pending_document_count,
                       (SELECT COUNT(*) FROM issues i WHERE i.project_id = p.id AND i.status = 'open') AS open_issue_count,
                       (SELECT MAX(c.analyzed_at) FROM document_analysis_cache c WHERE c.project_id = p.id) AS last_analyzed_at
                FROM projects p
                ORDER BY p.updated_at DESC, p.id DESC
                """
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

    def delete_project(self, project_id: int) -> int:
        with self.database.connect() as connection:
            row = connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise KeyError(f"Project not found: {project_id}")
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return project_id

    def add_document(
        self,
        project_id: int,
        path: Path,
        title: str,
        file_format: str,
        content_hash: str,
        content: str,
        chapter_index: int = 0,
        preserve_analysis: bool = False,
    ) -> StoryDocument:
        with self.database.connect() as connection:
            # A newly imported chapter is a draft addition. Callers that want
            # incremental analysis keep the published graph and decisions
            # visible until a replacement analysis commits atomically.
            if not preserve_analysis:
                self.archive_review(connection, project_id)
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
            cache_rows = connection.execute(
                """
                SELECT
                  documents.id AS document_id,
                  document_analysis_cache.content_hash AS analyzed_hash,
                  document_analysis_cache.analyzed_at AS analyzed_at,
                  COUNT(DISTINCT episode_entity_mentions.id) AS entity_count,
                  COUNT(DISTINCT episode_relations.id) AS relation_count,
                  COUNT(DISTINCT episode_claims.id) AS claim_count
                FROM documents
                LEFT JOIN document_analysis_cache
                  ON document_analysis_cache.document_id = documents.id
                LEFT JOIN episode_entity_mentions
                  ON episode_entity_mentions.document_id = documents.id
                LEFT JOIN episode_relations
                  ON episode_relations.document_id = documents.id
                LEFT JOIN episode_claims
                  ON episode_claims.document_id = documents.id
                WHERE documents.project_id = ?
                GROUP BY documents.id
                """,
                (project_id,),
            ).fetchall()
        status_by_document = {int(row["document_id"]): dict(row) for row in cache_rows}
        documents: list[StoryDocument] = []
        for row in rows:
            data = dict(row)
            status = status_by_document.get(int(data["id"]), {})
            analyzed_hash = str(status.get("analyzed_hash") or "")
            if not analyzed_hash:
                analysis_status = "pending"
            elif analyzed_hash == data["content_hash"]:
                analysis_status = "analyzed"
            else:
                analysis_status = "stale"
            data.update(
                {
                    "analysis_status": analysis_status,
                    "analyzed_at": status.get("analyzed_at"),
                    "analysis_entity_count": int(status.get("entity_count") or 0),
                    "analysis_relation_count": int(status.get("relation_count") or 0),
                    "analysis_claim_count": int(status.get("claim_count") or 0),
                }
            )
            documents.append(StoryDocument(**data))
        return documents

    def list_story_settings(self, project_id: int) -> list[StorySetting]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM story_settings WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
        return [StorySetting(**dict(row)) for row in rows]

    def add_story_setting(self, project_id: int, title: str, content: str, certainty: str) -> StorySetting:
        with self.database.connect() as connection:
            if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
                raise KeyError(project_id)
            cursor = connection.execute(
                "INSERT INTO story_settings(project_id,title,content,certainty) VALUES(?,?,?,?)",
                (project_id, title.strip(), content.strip(), certainty),
            )
            row = connection.execute("SELECT * FROM story_settings WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return StorySetting(**dict(row))

    def update_story_setting(self, setting_id: int, title: str, content: str, certainty: str) -> StorySetting:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM story_settings WHERE id = ?", (setting_id,)).fetchone()
            if row is None:
                raise KeyError(setting_id)
            connection.execute(
                "UPDATE story_settings SET title = ?, content = ?, certainty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title.strip(), content.strip(), certainty, setting_id),
            )
            row = connection.execute("SELECT * FROM story_settings WHERE id = ?", (setting_id,)).fetchone()
        return StorySetting(**dict(row))

    def delete_story_setting(self, setting_id: int) -> int:
        with self.database.connect() as connection:
            row = connection.execute("SELECT project_id FROM story_settings WHERE id = ?", (setting_id,)).fetchone()
            if row is None:
                raise KeyError(setting_id)
            connection.execute("DELETE FROM story_settings WHERE id = ?", (setting_id,))
        return int(row["project_id"])

    def list_foreshadowing_statuses(self, project_id: int) -> list[ForeshadowingStatus]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM foreshadowing_status WHERE project_id = ? ORDER BY entity_id",
                (project_id,),
            ).fetchall()
        return [ForeshadowingStatus(**dict(row)) for row in rows]

    def set_foreshadowing_status(self, project_id: int, entity_id: int, status: str) -> ForeshadowingStatus:
        with self.database.connect() as connection:
            entity = connection.execute(
                "SELECT id FROM entities WHERE id = ? AND project_id = ? AND type = 'foreshadowing'",
                (entity_id, project_id),
            ).fetchone()
            if entity is None:
                raise KeyError(entity_id)
            connection.execute(
                "INSERT INTO foreshadowing_status(entity_id, project_id, status) VALUES(?,?,?) "
                "ON CONFLICT(entity_id) DO UPDATE SET status = excluded.status, updated_at = CURRENT_TIMESTAMP",
                (entity_id, project_id, status),
            )
            row = connection.execute(
                "SELECT * FROM foreshadowing_status WHERE entity_id = ?", (entity_id,)
            ).fetchone()
        return ForeshadowingStatus(**dict(row))

    def get_document_analysis_cache(
        self,
        document_id: int,
        content_hash: str,
        model_name: str = "",
        prompt_version: str = "",
    ) -> dict | None:
        query = """
            SELECT payload
            FROM document_analysis_cache
            WHERE document_id = ? AND content_hash = ?
        """
        parameters: list[str | int] = [document_id, content_hash]
        if model_name or prompt_version:
            query += " AND model_name = ? AND prompt_version = ?"
            parameters.extend([model_name, prompt_version])
        with self.database.connect() as connection:
            row = connection.execute(
                query,
                parameters,
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload"]))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def upsert_document_analysis_cache(
        self,
        document_id: int,
        project_id: int,
        content_hash: str,
        payload: dict,
        model_name: str = "",
        prompt_version: str = "",
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO document_analysis_cache
                  (document_id, project_id, content_hash, model_name, prompt_version, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                  project_id = excluded.project_id,
                  content_hash = excluded.content_hash,
                  model_name = excluded.model_name,
                  prompt_version = excluded.prompt_version,
                  payload = excluded.payload,
                  analyzed_at = CURRENT_TIMESTAMP
                """,
                (document_id, project_id, content_hash, model_name, prompt_version, encode_json(payload)),
            )

    def delete_document(self, document_id: int) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Document not found: {document_id}")
            project_id = int(row["project_id"])
            self.archive_review(connection, project_id)
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            connection.execute("DELETE FROM relations WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM issues WHERE project_id = ?", (project_id,))
            connection.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (project_id,),
            )
        return project_id

    @staticmethod
    def evidence_fingerprint(rows):
        import hashlib
        values = sorted((row['document_id'], row['text']) for row in rows)
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()

    def archive_review(self, connection, project_id):
        for issue in connection.execute('SELECT * FROM issues WHERE project_id=?', (project_id,)).fetchall():
            ids = json.loads(issue['evidence_chunk_ids'])
            evidence = [dict(row) for row in connection.execute(
                'SELECT c.*,d.title,d.chapter_index FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.project_id=?', (project_id,)) if row['id'] in ids]
            connection.execute('INSERT INTO review_history(project_id,title,description,status,evidence,fingerprint) VALUES(?,?,?,?,?,?)',
                (project_id, issue['title'], issue['description'], issue['status'], json.dumps(evidence, ensure_ascii=False), self.evidence_fingerprint(evidence)))
        connection.execute('DELETE FROM issues WHERE project_id=?', (project_id,))
        connection.execute('DELETE FROM relations WHERE project_id=?', (project_id,))
        connection.execute('DELETE FROM entities WHERE project_id=?', (project_id,))

    def review_history(self, project_id):
        with self.database.connect() as connection:
            rows = connection.execute('SELECT * FROM review_history WHERE project_id=? ORDER BY id DESC', (project_id,)).fetchall()
        return [{**dict(row), 'evidence': json.loads(row['evidence'])} for row in rows]

    def replace_document(self, document_id, path, file_format, content_hash, content, chunks):
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone()
            if row is None:
                raise KeyError(document_id)
            if row['content_hash'] == content_hash:
                return StoryDocument(**dict(row))
            project_id = row['project_id']
            self.archive_review(connection, project_id)
            connection.execute('UPDATE documents SET path=?,format=?,content_hash=?,content=? WHERE id=?',
                (str(path), file_format, content_hash, content, document_id))
            # Retain the last analyzed hash/time to distinguish a revision from
            # a never-analyzed draft. Cache reads require the current content
            # hash, so the previous payload cannot be reused for this revision.
            for table in ('episode_claims', 'episode_relations', 'episode_entity_mentions'):
                connection.execute(f'DELETE FROM {table} WHERE document_id=?', (document_id,))
            self.replace_chunks(project_id, document_id, chunks, connection=connection)
            connection.execute('UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (project_id,))
            return StoryDocument(**dict(connection.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone()))

    def replace_chunks(self, project_id: int, document_id: int, chunks: list[str], connection=None) -> list[int]:
        with (nullcontext(connection) if connection is not None else self.database.connect()) as connection:
            document_row = connection.execute(
                "SELECT content FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            document_content = str(document_row["content"]) if document_row is not None else ""
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            ids: list[int] = []
            search_from = 0
            for index, text in enumerate(chunks):
                start_offset = document_content.find(text, search_from) if document_content else -1
                if start_offset < 0:
                    start_offset = search_from
                end_offset = start_offset + len(text)
                search_from = max(end_offset, search_from)
                cursor = connection.execute(
                    """
                    INSERT INTO chunks (document_id, project_id, chunk_index, text, start_offset, end_offset)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (document_id, project_id, index, text, start_offset, end_offset),
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

    def clear_episode_analysis(self, project_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM episode_claims WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM episode_relations WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM episode_entity_mentions WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM document_analysis_cache WHERE project_id = ?", (project_id,))

    def replace_episode_analysis(
        self,
        project_id: int,
        document_id: int,
        content_hash: str,
        payload: dict[str, Any],
        model_name: str = "",
        prompt_version: str = "",
    ) -> None:
        with self.database.connect() as connection:
            chunk_rows = connection.execute(
                "SELECT id FROM chunks WHERE document_id = ? ORDER BY chunk_index",
                (document_id,),
            ).fetchall()
            default_evidence = [int(row["id"]) for row in chunk_rows]
            connection.execute("DELETE FROM episode_claims WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM episode_relations WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM episode_entity_mentions WHERE document_id = ?", (document_id,))

            for raw_entity in payload.get("entities", []):
                if not isinstance(raw_entity, dict):
                    continue
                name = str(raw_entity.get("name", "")).strip()
                entity_type = str(raw_entity.get("type", "")).strip()
                if not name or not entity_type:
                    continue
                aliases = raw_entity.get("aliases", [])
                clean_aliases = [str(alias).strip() for alias in aliases if str(alias).strip()] if isinstance(aliases, list) else []
                confidence = _coerce_confidence(raw_entity.get("confidence", 0.7))
                evidence_ids = _coerce_int_list(raw_entity.get("evidence_chunk_ids")) or default_evidence[:2]
                connection.execute(
                    """
                    INSERT INTO episode_entity_mentions
                      (project_id, document_id, entity_type, name, aliases, summary, confidence, evidence_chunk_ids)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id, entity_type, name) DO UPDATE SET
                      aliases = excluded.aliases,
                      summary = excluded.summary,
                      confidence = excluded.confidence,
                      evidence_chunk_ids = excluded.evidence_chunk_ids
                    """,
                    (
                        project_id,
                        document_id,
                        entity_type,
                        name[:80],
                        encode_json(clean_aliases),
                        str(raw_entity.get("summary", ""))[:400],
                        confidence,
                        encode_json(evidence_ids),
                    ),
                )

            for raw_relation in payload.get("relations", []):
                if not isinstance(raw_relation, dict):
                    continue
                source = str(raw_relation.get("source", "")).strip()
                target = str(raw_relation.get("target", "")).strip()
                relation_type = normalize_relation_type(str(raw_relation.get("type", "")).strip())
                if not source or not target or source == target or not relation_type:
                    continue
                evidence_ids = _coerce_int_list(raw_relation.get("evidence_chunk_ids")) or default_evidence[:2]
                connection.execute(
                    """
                    INSERT INTO episode_relations
                      (project_id, document_id, source_name, target_name, type, confidence, evidence_chunk_ids)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id, source_name, target_name, type) DO UPDATE SET
                      confidence = excluded.confidence,
                      evidence_chunk_ids = excluded.evidence_chunk_ids
                    """,
                    (
                        project_id,
                        document_id,
                        source[:80],
                        target[:80],
                        relation_type,
                        _coerce_confidence(raw_relation.get("confidence", 0.7)),
                        encode_json(evidence_ids),
                    ),
                )

            for raw_issue in payload.get("issues", []):
                if not isinstance(raw_issue, dict):
                    continue
                title = str(raw_issue.get("title", "")).strip()
                description = str(raw_issue.get("description", "")).strip()
                if not title and not description:
                    continue
                evidence_ids = _coerce_int_list(raw_issue.get("evidence_chunk_ids")) or default_evidence[:2]
                connection.execute(
                    """
                    INSERT INTO episode_claims
                      (project_id, document_id, subject, claim_type, value, description, confidence, evidence_chunk_ids)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        document_id,
                        title[:120] or "설정 주장",
                        str(raw_issue.get("category", "contradiction"))[:80],
                        str(raw_issue.get("severity", "medium"))[:80],
                        description[:1000],
                        _coerce_confidence(raw_issue.get("confidence", 0.7)),
                        encode_json(evidence_ids),
                    ),
                )

            connection.execute(
                """
                INSERT INTO document_analysis_cache
                  (document_id, project_id, content_hash, model_name, prompt_version, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                  project_id = excluded.project_id,
                  content_hash = excluded.content_hash,
                  model_name = excluded.model_name,
                  prompt_version = excluded.prompt_version,
                  payload = excluded.payload,
                  analyzed_at = CURRENT_TIMESTAMP
                """,
                (document_id, project_id, content_hash, model_name, prompt_version, encode_json(payload)),
            )

    def episode_payload(
        self,
        project_id: int,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        where, parameters = self._document_range_filter(project_id, start_chapter, end_chapter)
        with self.database.connect() as connection:
            entity_rows = connection.execute(
                f"""
                SELECT episode_entity_mentions.*, documents.chapter_index
                FROM episode_entity_mentions
                JOIN documents ON documents.id = episode_entity_mentions.document_id
                WHERE {where}
                ORDER BY documents.chapter_index, documents.id, episode_entity_mentions.id
                """,
                parameters,
            ).fetchall()
            relation_rows = connection.execute(
                f"""
                SELECT episode_relations.*, documents.chapter_index
                FROM episode_relations
                JOIN documents ON documents.id = episode_relations.document_id
                WHERE {where}
                ORDER BY documents.chapter_index, documents.id, episode_relations.id
                """,
                parameters,
            ).fetchall()
            claim_rows = connection.execute(
                f"""
                SELECT episode_claims.*, documents.chapter_index
                FROM episode_claims
                JOIN documents ON documents.id = episode_claims.document_id
                WHERE {where}
                ORDER BY documents.chapter_index, documents.id, episode_claims.id
                """,
                parameters,
            ).fetchall()

        entities_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for row in entity_rows:
            data = dict(row)
            key = (str(data["entity_type"]), str(data["name"]))
            aliases = decode_json(data["aliases"])
            evidence_ids = decode_json(data["evidence_chunk_ids"])
            if key not in entities_by_key:
                entities_by_key[key] = {
                    "type": data["entity_type"],
                    "name": data["name"],
                    "summary": data["summary"],
                    "aliases": aliases,
                    "confidence": float(data["confidence"] or 0.7),
                    "_first_seen_document_id": int(data["document_id"]),
                    "_document_ids": [int(data["document_id"])],
                    "evidence_chunk_ids": evidence_ids,
                }
                continue
            existing = entities_by_key[key]
            existing_aliases = existing.setdefault("aliases", [])
            for alias in aliases:
                if alias not in existing_aliases:
                    existing_aliases.append(alias)
            if int(data["document_id"]) not in existing["_document_ids"]:
                existing["_document_ids"].append(int(data["document_id"]))
            for evidence_id in evidence_ids:
                if evidence_id not in existing["evidence_chunk_ids"]:
                    existing["evidence_chunk_ids"].append(evidence_id)
            existing["confidence"] = max(float(existing.get("confidence", 0.7)), float(data["confidence"] or 0.7))

        relations: list[dict[str, Any]] = []
        for row in relation_rows:
            data = dict(row)
            relations.append(
                {
                    "source": data["source_name"],
                    "target": data["target_name"],
                    "type": data["type"],
                    "confidence": float(data["confidence"] or 0.7),
                    "_document_id": int(data["document_id"]),
                    "evidence_chunk_ids": decode_json(data["evidence_chunk_ids"]),
                }
            )

        claims = []
        for row in claim_rows:
            data = dict(row)
            claims.append(
                {
                    "subject": data["subject"],
                    "type": data["claim_type"],
                    "value": data["value"],
                    "description": data["description"],
                    "confidence": float(data["confidence"] or 0.7),
                    "_document_id": int(data["document_id"]),
                    "evidence_chunk_ids": decode_json(data["evidence_chunk_ids"]),
                }
            )

        return {
            "entities": list(entities_by_key.values()),
            "relations": relations,
            "claims": claims,
            "issues": [],
        }

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
        data["claims"] = decode_json(data.get("claims", "[]"))
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

    def graph(
        self,
        project_id: int,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> GraphPayload:
        range_where, range_parameters = self._document_range_filter(project_id, start_chapter, end_chapter)
        with self.database.connect() as connection:
            cited_appearances = connection.execute(
                """SELECT m.entity_type,m.name,m.document_id FROM episode_entity_mentions m
                JOIN document_analysis_cache c ON c.document_id=m.document_id
                WHERE m.project_id=? AND c.prompt_version='gpt-evidence-graph-v1'""", (project_id,)
            ).fetchall()
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
                f"""
                SELECT id, content, chapter_index
                FROM documents
                WHERE {range_where}
                ORDER BY chapter_index, id
                """,
                range_parameters,
            ).fetchall()
            chunk_rows = connection.execute(
                f"""
                SELECT chunks.id, chunks.document_id
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                WHERE {range_where}
                ORDER BY documents.chapter_index, chunks.chunk_index
                """,
                range_parameters,
            ).fetchall()
        selected_document_ids = [int(row["id"]) for row in document_rows]
        selected_chunk_ids = {int(row["id"]) for row in chunk_rows}
        has_range_filter = start_chapter is not None or end_chapter is not None

        entities = []
        entity_payloads: list[dict[str, Any]] = []
        cited_docs = {}
        for appearance in cited_appearances:
            cited_docs.setdefault((appearance['entity_type'], appearance['name']), set()).add(appearance['document_id'])
        for row in entity_rows:
            data = dict(row)
            data["aliases"] = decode_json(data["aliases"])
            data["_evidence_document_ids"] = cited_docs.get((data["type"], data["name"]), set())
            entity_payloads.append(data)
        entity_metrics = _entity_story_metrics(entity_payloads, [dict(row) for row in document_rows])
        for data in entity_payloads:
            data.update(entity_metrics.get(int(data["id"]), {}))
            if has_range_filter and data.get("document_count", 0) <= 0:
                continue
            entities.append(EntityNode(**data))
        visible_entity_ids = {entity.id for entity in entities}
        relations = []
        for row in relation_rows:
            data = dict(row)
            data["claims"] = decode_json(data.get("claims", "[]"))
            if has_range_filter:
                # Do not show an explanation relying on evidence outside this range.
                data["claims"] = [claim for claim in data["claims"]
                    if claim.get("quotes") and all(q["chunk_id"] in selected_chunk_ids for q in claim["quotes"])]
            data["evidence_chunk_ids"] = decode_json(data["evidence_chunk_ids"])
            if has_range_filter:
                evidence_ids = set(_coerce_int_list(data["evidence_chunk_ids"]))
                if evidence_ids and not (evidence_ids & selected_chunk_ids):
                    continue
                if int(data["source_entity_id"]) not in visible_entity_ids or int(data["target_entity_id"]) not in visible_entity_ids:
                    continue
            if data.get("origin") != "gpt":
                data["type"] = normalize_relation_type(str(data["type"]))
            data.update(_relation_story_metrics(data, entity_metrics, len(document_rows)))
            relations.append(RelationEdge(**data))
        issues = []
        for row in issue_rows:
            data = dict(row)
            data["evidence_chunk_ids"] = decode_json(data["evidence_chunk_ids"])
            if has_range_filter:
                evidence_ids = set(_coerce_int_list(data["evidence_chunk_ids"]))
                if evidence_ids and not (evidence_ids & selected_chunk_ids):
                    continue
            issues.append(ContinuityIssue(**data))
        changes = self._relation_changes(project_id, selected_document_ids, visible_entity_ids)
        timeline = self._relation_timeline(project_id, selected_document_ids, visible_entity_ids)
        graph_range = GraphRange(
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            document_ids=selected_document_ids,
            document_count=len(selected_document_ids),
            continuity_ready=True,
            message="선택 범위의 설정 붕괴 후보를 판단합니다.",
        )
        entity_ids = {int(entity.id) for entity in entities}
        relation_endpoints = {
            endpoint
            for relation in relations
            for endpoint in (relation.source_entity_id, relation.target_entity_id)
            if endpoint in entity_ids
        }
        # Count valid connected components so the overview can distinguish one
        # coherent story network from several disconnected islands. Dangling
        # endpoints are intentionally excluded from this count and reported
        # separately below.
        adjacency: dict[int, set[int]] = {entity_id: set() for entity_id in entity_ids}
        for relation in relations:
            source, target = relation.source_entity_id, relation.target_entity_id
            if source in adjacency and target in adjacency and source != target:
                adjacency[source].add(target)
                adjacency[target].add(source)
        remaining = set(relation_endpoints)
        component_count = 0
        while remaining:
            component_count += 1
            queue = [remaining.pop()]
            for source in queue:
                for target in adjacency[source]:
                    if target in remaining:
                        remaining.remove(target)
                        queue.append(target)
        generic_types = {"관계", "관련", "co_occurs", "동시 등장"}
        generic_relation_count = sum(1 for relation in relations if relation.type in generic_types)
        unsupported_relation_count = sum(
            1 for relation in relations if not relation.evidence_chunk_ids and not relation.claims
        )
        pair_types: dict[tuple[int, int], set[str]] = {}
        for relation in relations:
            pair = tuple(sorted((relation.source_entity_id, relation.target_entity_id)))
            pair_types.setdefault(pair, set()).add(relation.type)
        conflicting_pair_count = sum(1 for types in pair_types.values() if relation_types_conflict(types))
        changed_pairs = {
            tuple(sorted((event.source_entity_id, event.target_entity_id)))
            for event in timeline
            if event.status == "changed"
        }
        explicit_break_pairs = {
            tuple(sorted((event.source_entity_id, event.target_entity_id)))
            for event in timeline
            if event.status == "explicit_break"
        }
        gap_pairs = {
            tuple(sorted((event.source_entity_id, event.target_entity_id)))
            for event in timeline
            if event.status == "gap" or event.gap_before
        }
        # A timeline extractor can omit the explicit gap flag. If the same
        # pair is observed again after one or more missing chapters, retain a
        # conservative review candidate so API health matches the graph UI.
        chapters_by_pair: dict[tuple[int, int], set[int]] = {}
        for event in timeline:
            pair = tuple(sorted((event.source_entity_id, event.target_entity_id)))
            chapters_by_pair.setdefault(pair, set()).add(event.chapter_index)
        for pair, chapters in chapters_by_pair.items():
            ordered = sorted(chapters)
            if any(right - left > 1 for left, right in zip(ordered, ordered[1:])):
                gap_pairs.add(pair)
        health = GraphHealth(
            connected_entity_count=len(relation_endpoints),
            component_count=component_count,
            isolated_entity_count=sum(1 for entity in entities if entity.id not in relation_endpoints),
            unsupported_relation_count=unsupported_relation_count,
            generic_relation_count=generic_relation_count,
            conflicting_pair_count=conflicting_pair_count,
            changed_relation_count=len(changed_pairs) if changed_pairs else len(changes),
            explicit_break_count=len(explicit_break_pairs),
            gap_relation_count=len(gap_pairs),
            dangling_relation_count=sum(
                1 for row in relation_rows
                if int(row["source_entity_id"]) not in visible_entity_ids
                or int(row["target_entity_id"]) not in visible_entity_ids
            ),
            message="근거·변화·고립 후보를 분리해 확인하세요.",
        )
        return GraphPayload(
            entities=entities,
            relations=relations,
            issues=issues,
            changes=changes,
            range=graph_range,
            health=health,
            timeline=timeline,
        )

    def open_issues(self, project_id: int) -> list[ContinuityIssue]:
        """Return open candidates for range-analysis merge bookkeeping."""
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM issues WHERE project_id=? AND status='open' ORDER BY id DESC",
                (project_id,),
            ).fetchall()
        values = []
        for row in rows:
            data = dict(row)
            data['evidence_chunk_ids'] = decode_json(data.get('evidence_chunk_ids'))
            values.append(ContinuityIssue(**data))
        return values

    def _relation_timeline(
        self, project_id: int, document_ids: list[int], visible_entity_ids: set[int]
    ) -> list[RelationTimelineEvent]:
        if not document_ids:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT episode_relations.*, documents.chapter_index
                FROM episode_relations JOIN documents ON documents.id = episode_relations.document_id
                WHERE episode_relations.project_id = ? AND episode_relations.document_id IN ({placeholders})
                ORDER BY documents.chapter_index, episode_relations.id
                """, [project_id, *document_ids]
            ).fetchall()
            entity_rows = connection.execute(
                "SELECT id, name, aliases FROM entities WHERE project_id = ?", (project_id,)
            ).fetchall()
        ids_by_term, ambiguous_terms = _unambiguous_entity_term_index(entity_rows)
        latest: dict[tuple[int, int], str] = {}
        last_chapter: dict[tuple[int, int], int] = {}
        events: list[RelationTimelineEvent] = []
        for row in rows:
            source_term = str(row["source_name"]).strip()
            target_term = str(row["target_name"]).strip()
            source_id = None if source_term in ambiguous_terms else ids_by_term.get(source_term)
            target_id = None if target_term in ambiguous_terms else ids_by_term.get(target_term)
            if source_id is None or target_id is None or source_id not in visible_entity_ids or target_id not in visible_entity_ids:
                continue
            relation_type = str(row["type"])
            pair = (source_id, target_id)
            explicit_break = any(term in relation_type for term in ("단절", "해제", "결별", "종료", "더 이상"))
            changed = pair in latest and latest[pair] != relation_type
            chapter_index = int(row["chapter_index"])
            has_gap = pair in last_chapter and chapter_index > last_chapter[pair] + 1
            status = "explicit_break" if explicit_break else ("changed" if changed else ("gap" if has_gap else "observed"))
            latest[pair] = relation_type
            last_chapter[pair] = chapter_index
            events.append(RelationTimelineEvent(
                source_entity_id=source_id,
                target_entity_id=target_id,
                source_name=str(row["source_name"]),
                target_name=str(row["target_name"]),
                relation_type=relation_type,
                chapter_index=chapter_index,
                document_id=int(row["document_id"]),
                evidence_chunk_ids=decode_json(row["evidence_chunk_ids"]),
                status=status,
                gap_before=has_gap,
            ))
        return events

    def _relation_changes(
        self,
        project_id: int,
        document_ids: list[int],
        visible_entity_ids: set[int],
    ) -> list[RelationChange]:
        if len(document_ids) < 2:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        with self.database.connect() as connection:
            entity_rows = connection.execute(
                "SELECT id, name, aliases FROM entities WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            relation_rows = connection.execute(
                f"""
                SELECT
                  episode_relations.*,
                  documents.chapter_index,
                  COALESCE(document_analysis_cache.prompt_version, '') AS graph_prompt_version
                FROM episode_relations
                JOIN documents ON documents.id = episode_relations.document_id
                LEFT JOIN document_analysis_cache ON document_analysis_cache.document_id = documents.id
                WHERE episode_relations.project_id = ?
                  AND episode_relations.document_id IN ({placeholders})
                ORDER BY documents.chapter_index, documents.id, episode_relations.id
                """,
                [project_id, *document_ids],
            ).fetchall()
        entity_ids_by_term, ambiguous_terms = _unambiguous_entity_term_index(entity_rows)
        names_by_id: dict[int, str] = {}
        for row in entity_rows:
            entity_id = int(row["id"])
            name = str(row["name"])
            names_by_id[entity_id] = name

        latest_by_pair: dict[tuple[int, int], dict[str, Any]] = {}
        changes: list[RelationChange] = []
        for row in relation_rows:
            data = dict(row)
            # Free-text GPT labels do not establish a change of the same relationship state.
            # Keep them as source-backed candidates until a typed temporal comparison exists.
            if data.get("graph_prompt_version") == "gpt-evidence-graph-v1":
                continue
            source_term = str(data["source_name"]).strip()
            target_term = str(data["target_name"]).strip()
            source_id = None if source_term in ambiguous_terms else entity_ids_by_term.get(source_term)
            target_id = None if target_term in ambiguous_terms else entity_ids_by_term.get(target_term)
            if source_id is None or target_id is None:
                continue
            if source_id not in visible_entity_ids or target_id not in visible_entity_ids:
                continue
            pair_key = (source_id, target_id)
            relation_type = normalize_relation_type(str(data["type"]))
            previous = latest_by_pair.get(pair_key)
            if previous is not None and previous["type"] != relation_type:
                evidence_ids = [
                    *_coerce_int_list(previous.get("evidence_chunk_ids")),
                    *_coerce_int_list(data.get("evidence_chunk_ids")),
                ]
                changes.append(
                    RelationChange(
                        id=len(changes) + 1,
                        project_id=project_id,
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        source_name=names_by_id.get(source_id, str(data["source_name"])),
                        target_name=names_by_id.get(target_id, str(data["target_name"])),
                        previous_type=str(previous["type"]),
                        current_type=relation_type,
                        previous_document_id=int(previous["document_id"]),
                        current_document_id=int(data["document_id"]),
                        description=(
                            f"{names_by_id.get(source_id, data['source_name'])}와 "
                            f"{names_by_id.get(target_id, data['target_name'])}의 관계가 "
                            f"{previous['type']}에서 {relation_type}(으)로 바뀌었습니다."
                        ),
                        evidence_chunk_ids=list(dict.fromkeys(evidence_ids)),
                    )
                )
            latest_by_pair[pair_key] = {
                "type": relation_type,
                "document_id": int(data["document_id"]),
                "evidence_chunk_ids": decode_json(data["evidence_chunk_ids"]),
            }
        return changes

    def _document_range_filter(
        self,
        project_id: int,
        start_chapter: int | None,
        end_chapter: int | None,
    ) -> tuple[str, list[int]]:
        clauses = ["documents.project_id = ?"]
        parameters = [project_id]
        if start_chapter is not None:
            clauses.append("documents.chapter_index >= ?")
            parameters.append(start_chapter)
        if end_chapter is not None:
            clauses.append("documents.chapter_index <= ?")
            parameters.append(end_chapter)
        return " AND ".join(clauses), parameters

    def create_job(
        self,
        project_id: int,
        status: AnalysisStatus,
        message: str,
        current_step: str = "queued",
        progress: int = 0,
    ) -> AnalysisJob:
        progress = clamp_progress(progress)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_jobs (project_id, status, current_step, progress, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, status.value, current_step, progress, message),
            )
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return AnalysisJob(**dict(row))

    def create_running_analysis_job(
        self,
        project_id: int,
        message: str,
        current_step: str = "queued",
        progress: int = 0,
        review_context: dict | None = None,
    ) -> AnalysisJob:
        progress = clamp_progress(progress)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            running = connection.execute(
                """
                SELECT *
                FROM analysis_jobs
                WHERE project_id = ? AND status = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (project_id, AnalysisStatus.running.value),
            ).fetchone()
            if running is not None:
                raise RuntimeError("이미 분석이 진행 중입니다. 완료되거나 취소된 뒤 다시 실행해 주세요.")
            cursor = connection.execute(
                """
                INSERT INTO analysis_jobs (project_id, status, current_step, progress, message, review_context)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, AnalysisStatus.running.value, current_step, progress, message, encode_json(review_context or {})),
            )
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return AnalysisJob(**dict(row))

    def update_job(
        self,
        job_id: int,
        status: AnalysisStatus,
        message: str,
        current_step: str | None = None,
        progress: int | None = None,
    ) -> AnalysisJob:
        progress_value = clamp_progress(progress) if progress is not None else None
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?,
                    message = ?,
                    current_step = COALESCE(?, current_step),
                    progress = COALESCE(?, progress),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, message, current_step, progress_value, job_id),
            )
            row = connection.execute("SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        return AnalysisJob(**dict(row))

    def update_running_job(
        self,
        job_id: int,
        status: AnalysisStatus,
        message: str,
        current_step: str | None = None,
        progress: int | None = None,
    ) -> AnalysisJob:
        progress_value = clamp_progress(progress) if progress is not None else None
        with self.database.connect() as connection:
            closed_details = None
            if status in (AnalysisStatus.failed, AnalysisStatus.cancelled):
                connection.execute('BEGIN IMMEDIATE')
                pending = connection.execute('SELECT window_details FROM analysis_jobs WHERE id=? AND status=?',
                                             (job_id, AnalysisStatus.running.value)).fetchone()
                if pending is not None:
                    closed_details = close_unfinished_windows(pending['window_details'], message)
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?,
                    message = ?,
                    current_step = COALESCE(?, current_step),
                    progress = COALESCE(?, progress),
                    window_details = COALESCE(?, window_details),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (
                    status.value,
                    message,
                    current_step,
                    progress_value,
                    closed_details,
                    job_id,
                    AnalysisStatus.running.value,
                ),
            )
            row = connection.execute("SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Analysis job not found: {job_id}")
        return AnalysisJob(**dict(row))

    def get_job(self, job_id: int) -> AnalysisJob | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        return AnalysisJob(**dict(row)) if row is not None else None

    def latest_analysis_job(self, project_id: int) -> AnalysisJob | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM analysis_jobs
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        return AnalysisJob(**dict(row)) if row is not None else None

    def running_analysis_job(self, project_id: int) -> AnalysisJob | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM analysis_jobs
                WHERE project_id = ? AND status = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (project_id, AnalysisStatus.running.value),
            ).fetchone()
        return AnalysisJob(**dict(row)) if row is not None else None

    def mark_running_jobs_interrupted(self) -> int:
        message = "이전 실행이 종료되어 분석이 중단되었습니다. 다시 분석을 실행해 주세요."
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            pending = connection.execute('SELECT id,window_details FROM analysis_jobs WHERE status=?',
                                         (AnalysisStatus.running.value,)).fetchall()
            for row in pending:
                connection.execute("""UPDATE analysis_jobs SET status=?,current_step='failed',message=?,
                    window_details=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (AnalysisStatus.failed.value, message, close_unfinished_windows(row['window_details'], message), row['id']))
        return len(pending)

    def cancel_analysis(self, project_id: int, preserve_results: bool = False) -> AnalysisJob:
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                """
                SELECT *
                FROM analysis_jobs
                WHERE project_id = ? AND status = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (project_id, AnalysisStatus.running.value),
            ).fetchone()
            if row is None:
                latest = connection.execute(
                    """
                    SELECT *
                    FROM analysis_jobs
                    WHERE project_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (project_id,),
                ).fetchone()
                if latest is not None and latest["status"] == AnalysisStatus.cancelled.value:
                    job_id = int(latest["id"])
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO analysis_jobs (project_id, status, current_step, progress, message)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            project_id,
                            AnalysisStatus.cancelled.value,
                            "cancelled",
                            100,
                            "GPT 분석을 취소했습니다. 이전 결과는 유지됩니다." if preserve_results else "분석이 취소되어 생성 중이던 내용이 삭제되었습니다.",
                        ),
                    )
                    job_id = int(cursor.lastrowid)
            else:
                job_id = int(row["id"])
                pending = connection.execute('SELECT id,window_details FROM analysis_jobs WHERE project_id=? AND status=?',
                                             (project_id, AnalysisStatus.running.value)).fetchall()
                connection.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = ?,
                        current_step = ?,
                        message = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ? AND status = ?
                    """,
                    (
                        AnalysisStatus.cancelled.value,
                        "cancelled",
                        "GPT 분석을 취소했습니다. 이전 결과는 유지됩니다." if preserve_results else "분석이 취소되어 생성 중이던 내용이 삭제되었습니다.",
                        project_id,
                        AnalysisStatus.running.value,
                    ),
                )
                for stopped in pending:
                    connection.execute('UPDATE analysis_jobs SET window_details=? WHERE id=?',
                        (close_unfinished_windows(stopped['window_details'], '분석을 취소하여 이 구간의 처리가 중단되었습니다.'), stopped['id']))
            if not preserve_results:
                connection.execute("DELETE FROM relations WHERE project_id = ?", (project_id,))
                connection.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
                connection.execute("DELETE FROM issues WHERE project_id = ?", (project_id,))
            cancelled = connection.execute(
                "SELECT * FROM analysis_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return AnalysisJob(**dict(cancelled))

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


def clamp_progress(progress: int) -> int:
    return max(0, min(100, int(progress)))


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.7
    return max(0.0, min(confidence, 1.0))


def _coerce_int_list(value: Any) -> list[int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


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
    if any(
        term in normalized
        for term in ("member", "belongs", "organization", "leader", "contains", "affiliated", "under")
    ) or any(
        term in value for term in ("소속", "조직", "대표", "관할", "산하", "휘하", "본부", "거점", "所屬", "所属")
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
            if int(document["id"]) in entity.get("_evidence_document_ids", set()):
                count = max(1, count)
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
