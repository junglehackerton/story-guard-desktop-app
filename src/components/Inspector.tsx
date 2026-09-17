import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type {
  ContinuityIssue,
  EntityNode,
  EntityRelationshipDetail,
  EvidenceChunk,
  GraphRange,
  IssueStatus,
  RelationChange,
  StoryDocument,
} from "../lib/types";
import { ENTITY_TYPE_LABELS, ISSUE_CATEGORY_LABELS, ISSUE_STATUS_LABELS } from "../lib/labels";

interface InspectorProps {
  hasGptRelations?: boolean;
  entity: EntityNode | null;
  relationships: EntityRelationshipDetail[];
  issues: ContinuityIssue[];
  changes: RelationChange[];
  graphRange: GraphRange;
  evidenceByIssueId: Record<number, EvidenceChunk[]>;
  onIssueStatus: (issueId: number, status: IssueStatus) => void;
}

const APPEARANCE_LABELS: Record<EntityNode["appearance_state"], string> = {
  new: "갑작스런 등장",
  active: "활성",
  fading: "언급 감소",
  dormant: "언급 소실",
};

export function Inspector({
  hasGptRelations = false,
  entity,
  relationships,
  issues,
  changes,
  graphRange,
  evidenceByIssueId,
  onIssueStatus,
}: InspectorProps) {
  return (
    <aside className="inspector">
      <section className="panel">
        <h2>선택 상세</h2>
        {entity ? (
          <div className="entity-detail">
            <span className={`entity-type entity-${entity.type}`}>
              {entity.is_unresolved ? '미확인 대상 · 분석 확인 필요' : ENTITY_TYPE_LABELS[entity.type]}
            </span>
            <h3>{entity.name}</h3>
            <p>{entity.summary}</p>
            <div className="entity-metrics">
              <span>{APPEARANCE_LABELS[entity.appearance_state]}</span>
              <span>언급 {entity.mention_count}회</span>
              <span>{entity.document_count}편 등장</span>
            </div>
            {entity.aliases.length > 0 && <p>별칭: {entity.aliases.join(", ")}</p>}
            <div className="entity-relations">
              <div className="entity-relations-title">
                <strong>연결된 관계</strong>
                <span>{relationships.length}</span>
              </div>
              {relationships.length === 0 ? (
                <p className="muted">현재 필터에서 연결된 관계가 없습니다.</p>
              ) : (
                relationships.map((detail) => (
                  <article key={detail.relation.id} className="entity-relation-card">
                    <div>
                      <span className={`entity-type entity-${detail.other.type}`}>
                        {ENTITY_TYPE_LABELS[detail.other.type]}
                      </span>
                      <strong>{detail.other.name}</strong>
                    </div>
                    <p>{detail.explanation}</p>
                    {detail.relation.id > 0 && <RelationEvidence relationId={detail.relation.id} />}
                  </article>
                ))
              )}
            </div>
          </div>
        ) : (
          <p className="muted">그래프 노드를 선택하면 설정 상세와 근거가 표시됩니다.</p>
        )}
      </section>

      <section className="panel issue-panel">
        <div className="panel-title-row">
          <h2>관계 변화</h2>
          <span>{changes.length}</span>
        </div>
        <div className="issue-list">
          {changes.length === 0 ? (
            <p className="muted">{hasGptRelations ? "GPT가 자유 문구로 추출한 관계는 변화로 확정하지 않습니다. 선택한 관계의 회차별 원문을 확인해 주세요." : "선택 범위에서 뚜렷한 관계 변화가 없습니다."}</p>
          ) : (
            changes.map((change) => (
              <article key={change.id} className="change-card">
                <strong>
                  {change.source_name} - {change.target_name}
                </strong>
                <p>{change.description}</p>
                <div className="change-types">
                  <span>{change.previous_type}</span>
                  <span>{change.current_type}</span>
                </div>
              </article>
            ))
          )}
        </div>
      </section>

      <section className="panel issue-panel">
        <div className="panel-title-row">
          <h2>설정 붕괴 리포트</h2>
          <span>{issues.length}</span>
        </div>
        <div className="issue-list">
          {issues.length === 0 ? (
            <p className="muted">열린 이슈가 없습니다.</p>
          ) : (
            issues.map((issue) => (
              <article key={issue.id} className={`issue-card severity-${issue.severity}`}>
                <div className="issue-card-header">
                  <strong>{issue.title}</strong>
                  <span>{ISSUE_CATEGORY_LABELS[issue.category] ?? issue.category}</span>
                </div>
                <p>{issue.description}</p>
                {(evidenceByIssueId[issue.id] ?? []).slice(0, 2).map((chunk) => (
                  <blockquote key={chunk.id}>{chunk.text}</blockquote>
                ))}
                <div className="issue-actions">
                  {(Object.keys(ISSUE_STATUS_LABELS) as IssueStatus[]).map((status) => (
                    <button
                      key={status}
                      className={issue.status === status ? "active" : ""}
                      onClick={() => onIssueStatus(issue.id, status)}
                    >
                      {ISSUE_STATUS_LABELS[status]}
                    </button>
                  ))}
                </div>
              </article>
            ))
          )}
        </div>
      </section>
    </aside>
  );
}


export function RelationEvidence({ relationId, expanded = false, onOpenDocument, documents = [] }: { relationId: number; expanded?: boolean; onOpenDocument?: (id: number, quote?: string) => void; documents?: StoryDocument[] }) {
  const [chunks, setChunks] = useState<EvidenceChunk[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [showAll, setShowAll] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setChunks(null); setError(""); setShowAll(false);
    api.relationEvidence(relationId).then(value => { if (!cancelled) setChunks(value); })
      .catch(() => { if (!cancelled) setError("원문 근거를 불러오지 못했습니다. 노드를 다시 선택해 주세요."); });
    return () => { cancelled = true; };
  }, [relationId, attempt]);
  return <details className="relation-evidence" open={expanded || undefined}>
    <summary>원문 근거 보기</summary>
    {error ? <div role="alert"><p>{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>다시 시도</button></div> : chunks === null ? <p>근거를 불러오는 중…</p>
      : chunks.length === 0 ? <p>저장된 원문 근거가 없습니다.</p>
      : <>
        {(showAll ? chunks : chunks.slice(0, 3)).map(chunk => { const document = documents.find(item => item.id === chunk.document_id); return <blockquote key={chunk.id}><small>{document ? `${document.chapter_index + 1}화 · ${document.title}` : `원문 구간 ${chunk.chunk_index + 1}`}</small><p>{chunk.text}</p>{onOpenDocument && <button className="text-action" onClick={() => onOpenDocument(chunk.document_id, chunk.text)}>이 회차 원고 열기</button>}</blockquote>; })}
        {chunks.length > 3 && <button type="button" className="text-action evidence-toggle" aria-expanded={showAll} onClick={() => setShowAll(value => !value)}>{showAll ? "근거 접기" : `근거 ${chunks.length - 3}개 더 보기`}</button>}
      </>}
  </details>;
}
