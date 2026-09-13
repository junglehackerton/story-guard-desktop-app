"""Validate source-backed graph candidates and store them in the analysis transaction."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from backend.app.models import EntityType


class EvidenceQuote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chunk_id: StrictInt
    quote: str = Field(min_length=2, max_length=1800)


class GraphEntity(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=80)
    type: EntityType
    name: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1000)
    evidence: list[EvidenceQuote] = Field(min_length=1, max_length=5)


class GraphRelation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    type: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=8, max_length=1000)
    basis: Literal['explicit', 'inferred']
    evidence: list[EvidenceQuote] = Field(min_length=1, max_length=5)


class GroundedGraph:
    def __init__(self):
        self.entities = {}
        self.relations = {}
        self.claims = {}

    @staticmethod
    def _evidence(quotes, context):
        ids = set()
        for quote in quotes:
            source = context.get(quote.chunk_id, {}).get('text', '')
            if not source:
                continue
            if quote.quote not in source:
                # GPT responses often preserve the words but normalize a
                # paragraph break to a space (or vice versa). Match only
                # whitespace differences, then replace the response with the
                # exact slice from the source so highlighting remains safe.
                words = re.findall(r'\S+', unicodedata.normalize('NFC', quote.quote))
                if not words:
                    continue
                pattern = r'\s+'.join(re.escape(word) for word in words)
                match = re.search(pattern, unicodedata.normalize('NFC', source))
                if match is None:
                    # Models may also normalize Korean punctuation (for
                    # example quote marks or a comma) while preserving every
                    # lexical character. Permit non-word separators only;
                    # never accept a paraphrase or reordered text.
                    compact = ''.join(ch for ch in unicodedata.normalize('NFC', quote.quote) if ch.isalnum() or ch == '_')
                    if compact:
                        loose = r'\W*'.join(re.escape(ch) for ch in compact)
                        match = re.search(loose, unicodedata.normalize('NFC', source))
                if match is None:
                    continue
                quote.quote = source[match.start():match.end()]
            ids.add(quote.chunk_id)
        return ids

    @staticmethod
    def _label(value: str) -> str:
        """Canonicalize model labels so whitespace/unicode variants merge."""
        return " ".join(unicodedata.normalize('NFC', value).strip().split())

    def add(self, entities, relations, context, current_chunk_id):
        references = {}
        pending_entities = {}
        selected_keys = set()
        for entity in entities:
            if entity.id in references:
                raise RuntimeError('관계 지도에 중복 엔티티 참조가 있습니다.')
            name = unicodedata.normalize('NFC', entity.name.strip())
            if not name:
                raise RuntimeError('관계 지도 엔티티 이름이 비어 있습니다.')
            key = (entity.type, name)
            references[entity.id] = key
            ids = self._evidence(entity.evidence, context)
            pending_entities.setdefault(key, {'summary': entity.summary, 'ids': set()})['ids'].update(ids)
            if current_chunk_id in ids:
                selected_keys.add(key)
        for relation in relations:
            if relation.source not in references or relation.target not in references:
                raise RuntimeError('관계 지도의 연결 대상이 추출된 엔티티에 없습니다.')
            source, target = references[relation.source], references[relation.target]
            relation_label = self._label(relation.type)
            if source == target or not relation_label:
                raise RuntimeError('관계 지도의 연결 또는 관계 이름이 올바르지 않습니다.')
            if relation_label.casefold() in {'관계', '관련', '관련됨', 'related', 'related_to', 'co_occurs'}:
                raise RuntimeError('관계 유형에 구체적인 행동이나 상태가 필요합니다.')
            if not relation.explanation.strip():
                raise RuntimeError('관계 설명이 비어 있습니다.')
            ids = self._evidence(relation.evidence, context)
            if current_chunk_id not in ids:
                continue
            selected_keys.update((source, target))
            key = (source, target, relation_label)
            self.relations.setdefault(key, set()).update(ids)
            claim = {'explanation': relation.explanation.strip(), 'basis': relation.basis,
                     'quotes': [quote.model_dump() for quote in relation.evidence]}
            if claim not in self.claims.setdefault(key, []):
                self.claims[key].append(claim)
        for key in selected_keys:
            entity = pending_entities[key]
            if key not in self.entities:
                self.entities[key] = {"summary": entity["summary"], "ids": set()}
            self.entities[key]["ids"].update(entity["ids"])

    def store(self, db, project_id, rows, documents, model, effort):
        """Called only inside the caller's successful snapshot-checked transaction."""
        by_id = {row['id']: row for row in rows}
        doc_order = {doc.id: (doc.chapter_index, doc.id) for doc in documents}
        entity_ids = {}
        db.execute('DELETE FROM relations WHERE project_id=?', (project_id,))
        for table in ('episode_entity_mentions', 'episode_relations', 'episode_claims', 'document_analysis_cache'):
            db.execute(f'DELETE FROM {table} WHERE project_id=?', (project_id,))
        for (kind, name), entity in self.entities.items():
            ids = sorted(entity['ids'])
            doc_ids = {by_id[value]['document_id'] for value in ids}
            first = min(doc_ids, key=lambda value: doc_order[value])
            db.execute('''INSERT INTO entities(project_id,type,name,aliases,summary,first_seen_document_id)
                VALUES(?,?,?,'[]',?,?) ON CONFLICT(project_id,type,name) DO UPDATE SET
                summary=excluded.summary,first_seen_document_id=excluded.first_seen_document_id''',
                (project_id, kind, name, entity['summary'], first))
            entity_ids[(kind, name)] = db.execute('SELECT id FROM entities WHERE project_id=? AND type=? AND name=?',
                (project_id, kind, name)).fetchone()['id']
            for doc_id in doc_ids:
                evidence = [value for value in ids if by_id[value]['document_id'] == doc_id]
                db.execute('''INSERT INTO episode_entity_mentions(project_id,document_id,entity_type,name,summary,evidence_chunk_ids)
                    VALUES(?,?,?,?,?,?)''', (project_id, doc_id, kind, name, entity['summary'], json.dumps(evidence)))
        # Retain IDs for unchanged nodes, removing nodes absent from the new full analysis.
        old_ids = [row['id'] for row in db.execute('SELECT id FROM entities WHERE project_id=?', (project_id,))]
        keep = set(entity_ids.values())
        db.executemany('DELETE FROM entities WHERE id=?', [(value,) for value in old_ids if value not in keep])
        episodes = {}
        for (source, target, label), evidence_ids in self.relations.items():
            ids = sorted(evidence_ids)
            claims = self.claims[(source, target, label)]
            for claim in claims:
                for quote in claim['quotes']:
                    quote['document_id'] = by_id[quote['chunk_id']]['document_id']
                    quote['chapter_index'] = doc_order[quote['document_id']][0]
            db.execute('''INSERT INTO relations(project_id,source_entity_id,target_entity_id,type,confidence,evidence_chunk_ids,origin,claims)
                VALUES(?,?,?,?,0.7,?,'gpt',?)''', (project_id, entity_ids[source], entity_ids[target], label, json.dumps(ids), json.dumps(claims, ensure_ascii=False)))
            for value in ids:
                key = (by_id[value]['document_id'], source[1], target[1], label)
                episodes.setdefault(key, set()).add(value)
        for (doc_id, source, target, label), ids in episodes.items():
            db.execute('''INSERT INTO episode_relations(project_id,document_id,source_name,target_name,type,evidence_chunk_ids)
                VALUES(?,?,?,?,?,?)''', (project_id, doc_id, source, target, label, json.dumps(sorted(ids))))
        for doc in documents:
            db.execute('''INSERT INTO document_analysis_cache(document_id,project_id,content_hash,model_name,prompt_version,payload)
                VALUES(?,?,?,?,?,?)''', (doc.id, project_id, doc.content_hash, model, 'gpt-evidence-graph-v1',
                    json.dumps({'provider': 'gpt', 'effort': effort})))
