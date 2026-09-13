import type { RelationEdge } from './types';

export interface GroupedRelationship {
  representative: RelationEdge;
  count: number;
  evidenceCount: number;
  claimCount: number;
  origins: Set<string>;
}

/** Collapse repeated claims for the same unordered entity pair and meaning. */
export function groupRelationshipEdges(edges: RelationEdge[]): GroupedRelationship[] {
  const groups = new Map<string, GroupedRelationship>();
  for (const relation of edges) {
    const pair = [relation.source_entity_id, relation.target_entity_id].sort((a, b) => a - b).join(':');
    const predicate = (relation.display_label || relation.type || '관계').trim().toLocaleLowerCase();
    const key = `${pair}:${predicate}`;
    const current = groups.get(key);
    if (!current) {
      groups.set(key, {
        representative: relation,
        count: 1,
        evidenceCount: relation.evidence_chunk_ids.length,
        claimCount: relation.claims?.length ?? 0,
        origins: new Set<string>(relation.origin ? [relation.origin] : []),
      });
      continue;
    }
    current.count += 1;
    current.evidenceCount += relation.evidence_chunk_ids.length;
    current.claimCount += relation.claims?.length ?? 0;
    if (relation.origin) current.origins.add(relation.origin);
    const score = (candidate: RelationEdge) =>
      (candidate.evidence_chunk_ids.length ? 4 : 0) +
      (candidate.claims?.length ? 3 : 0) +
      (candidate.is_weak ? 0 : 2) +
      candidate.confidence;
    if (score(relation) > score(current.representative)) current.representative = relation;
  }
  return [...groups.values()].sort((a, b) => a.representative.id - b.representative.id);
}
