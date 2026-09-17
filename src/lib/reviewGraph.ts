import type { ContinuityIssue, RelationEdge } from './types';

export interface ReviewGraphFocus { issueId: number; chunkId?: number }
export const judgmentLabel = { open: '확인 대기', accepted: '문제 있음', ignored: '문제 아님', deferred: '판단 보류' };

export function relatedRelations(relations: RelationEdge[], chunkIds: number[]) {
  const ids = new Set(chunkIds);
  const score = (relation: RelationEdge) => new Set([
    ...relation.evidence_chunk_ids,
    ...(relation.claims ?? []).flatMap(claim => claim.quotes.map(quote => quote.chunk_id)),
  ].filter(id => ids.has(id))).size;
  return relations.filter(relation => score(relation) > 0).sort((a, b) => score(b) - score(a) || a.id - b.id);
}

export function relationJudgments(relation: RelationEdge, issues: ContinuityIssue[]) {
  return issues.filter(issue => relatedRelations([relation], issue.evidence_chunk_ids).length > 0);
}
