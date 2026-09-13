import type { GraphPayload, RelationEdge } from "./types";

export function relationPairKey(sourceId: number, targetId: number) {
  return [sourceId, targetId].sort((a, b) => a - b).join(":");
}

/**
 * Detect opposing claims without requiring the extractor to emit one exact
 * pair of taxonomy labels. The result is deliberately a review candidate:
 * temporal context and negation still belong in the evidence panel.
 */
export function relationTypesConflict(types: Iterable<string>) {
  const labels = [...types].map((value) => value.trim().toLowerCase());
  const positive = labels.some((value) =>
    /동행|협력|동맹|친구|보호|신뢰|계약\s*체결|소유함|허용|승인|ally|friend|protect|trust|agreed|owns?|allows?/.test(value),
  );
  const negative = labels.some((value) =>
    /적대|대립|배신|의심|충돌|거절|계약\s*(?:해지|파기|거부)|계약\s*없이|사용\s*불가|금지|소유하지|enemy|hostile|betray|suspect|conflict|refus|reject|forbidden|without/.test(value),
  );
  return positive && negative;
}

export function isDanglingRelation(relation: RelationEdge, entityIds: ReadonlySet<number>) {
  return !entityIds.has(relation.source_entity_id) || !entityIds.has(relation.target_entity_id);
}

export function countDanglingRelations(graph: GraphPayload) {
  const entityIds = new Set(graph.entities.map(entity => entity.id));
  return graph.relations.filter(relation => isDanglingRelation(relation, entityIds)).length;
}

/** Number of connected relationship islands, excluding isolated entities and
 * dangling endpoints. The overview uses this to distinguish a fragmented
 * story graph from a single coherent network. */
export function countConnectedComponents(graph: GraphPayload) {
  const entityIds = new Set(graph.entities.map(entity => entity.id));
  const adjacency = new Map(graph.entities.map(entity => [entity.id, new Set<number>()]));
  const connected = new Set<number>();
  for (const relation of graph.relations) {
    if (relation.source_entity_id === relation.target_entity_id || isDanglingRelation(relation, entityIds)) continue;
    adjacency.get(relation.source_entity_id)!.add(relation.target_entity_id);
    adjacency.get(relation.target_entity_id)!.add(relation.source_entity_id);
    connected.add(relation.source_entity_id);
    connected.add(relation.target_entity_id);
  }
  const remaining = new Set(connected);
  let count = 0;
  while (remaining.size) {
    count += 1;
    const queue = [remaining.values().next().value as number];
    remaining.delete(queue[0]);
    for (let index = 0; index < queue.length; index += 1) {
      for (const next of adjacency.get(queue[index]) ?? []) {
        if (remaining.delete(next)) queue.push(next);
      }
    }
  }
  return count;
}

/** Return the drawable relationship islands with their member and edge IDs.
 * Missing endpoints and self-links are diagnostics, not part of a connected
 * component. The result is deterministic so the component picker does not
 * jump when the API returns entities in a different order. */
export function relationshipComponents(graph: GraphPayload) {
  const entityIds = new Set(graph.entities.map((entity) => entity.id));
  const adjacency = new Map(graph.entities.map((entity) => [entity.id, new Set<number>()]));
  for (const relation of graph.relations) {
    if (relation.source_entity_id === relation.target_entity_id || isDanglingRelation(relation, entityIds)) continue;
    adjacency.get(relation.source_entity_id)!.add(relation.target_entity_id);
    adjacency.get(relation.target_entity_id)!.add(relation.source_entity_id);
  }
  const remaining = new Set([...adjacency.keys()].sort((left, right) => left - right));
  const components: Array<{ entityIds: number[]; relationIds: number[]; anchorId: number }> = [];
  while (remaining.size) {
    const seed = remaining.values().next().value as number;
    if (!(adjacency.get(seed)?.size ?? 0)) {
      remaining.delete(seed);
      continue;
    }
    const queue = [seed];
    const members: number[] = [];
    remaining.delete(seed);
    for (let index = 0; index < queue.length; index += 1) {
      const current = queue[index];
      members.push(current);
      for (const next of [...(adjacency.get(current) ?? [])].sort((left, right) => left - right)) {
        if (remaining.delete(next)) queue.push(next);
      }
    }
    const memberSet = new Set(members);
    const edges = graph.relations
      .filter((relation) => memberSet.has(relation.source_entity_id) && memberSet.has(relation.target_entity_id))
      .map((relation) => relation.id)
      .sort((left, right) => left - right);
    const degree = new Map<number, number>();
    for (const relation of graph.relations) {
      if (!memberSet.has(relation.source_entity_id) || !memberSet.has(relation.target_entity_id)) continue;
      degree.set(relation.source_entity_id, (degree.get(relation.source_entity_id) ?? 0) + 1);
      degree.set(relation.target_entity_id, (degree.get(relation.target_entity_id) ?? 0) + 1);
    }
    const sortedMembers = members.sort((left, right) => left - right);
    const anchorId = [...sortedMembers].sort((left, right) => (degree.get(right) ?? 0) - (degree.get(left) ?? 0) || left - right)[0];
    components.push({ entityIds: sortedMembers, relationIds: edges, anchorId });
  }
  return components.sort((left, right) => right.entityIds.length - left.entityIds.length || left.entityIds[0] - right.entityIds[0]);
}

export function temporalIssuePairs(graph: GraphPayload) {
  return new Set(
    (graph.timeline ?? [])
      .filter((event) => event.status !== "observed")
      .map((event) => relationPairKey(event.source_entity_id, event.target_entity_id)),
  );
}

export function timelinePairsByStatus(graph: GraphPayload, status: "changed" | "gap" | "explicit_break") {
  const timeline = graph.timeline ?? [];
  const pairs = new Set(
    timeline
      .filter((event) => event.status === status || (status === "gap" && event.gap_before))
      .map((event) => relationPairKey(event.source_entity_id, event.target_entity_id)),
  );

  // A model can miss the explicit `gap` label while still returning evidence
  // for the same relationship in non-adjacent chapters. Treat that jump as a
  // review candidate, but only for the gap metric; a chapter jump alone never
  // becomes a confirmed contradiction or a broken relationship.
  if (status === "gap") {
    const chaptersByPair = new Map<string, number[]>();
    for (const event of timeline) {
      const key = relationPairKey(event.source_entity_id, event.target_entity_id);
      const chapters = chaptersByPair.get(key) ?? [];
      chapters.push(event.chapter_index);
      chaptersByPair.set(key, chapters);
    }
    for (const [pair, chapters] of chaptersByPair) {
      const ordered = [...new Set(chapters)].sort((left, right) => left - right);
      if (ordered.some((chapter, index) => index > 0 && chapter - ordered[index - 1] > 1)) {
        pairs.add(pair);
      }
    }
  }
  return pairs;
}

export function isRelationshipHealthIssue(relation: RelationEdge, issuePairs: Set<string>) {
  return (
    relation.is_weak ||
    relation.type === "관계" ||
    relation.type === "관련" ||
    (!relation.evidence_chunk_ids.length && !relation.claims?.length) ||
    issuePairs.has(relationPairKey(relation.source_entity_id, relation.target_entity_id))
  );
}
