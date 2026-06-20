import type {
  ContinuityIssue,
  EntityNode,
  EntityRelationshipDetail,
  EvidenceChunk,
  GraphRange,
  IssueStatus,
  RelationChange,
} from "../lib/types";
import { ENTITY_TYPE_LABELS, ISSUE_CATEGORY_LABELS, ISSUE_STATUS_LABELS } from "../lib/labels";

interface InspectorProps {
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
              {ENTITY_TYPE_LABELS[entity.type]}
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
                <strong>활성 관계</strong>
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
            <p className="muted">선택 범위에서 뚜렷한 관계 변화가 없습니다.</p>
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
          {!graphRange.continuity_ready ? (
            <p className="muted">{graphRange.message}</p>
          ) : issues.length === 0 ? (
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
