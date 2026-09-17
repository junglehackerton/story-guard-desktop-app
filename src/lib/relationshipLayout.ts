import type { EntityNode, GraphPayload, RelationEdge } from './types';
import type { GraphPosition } from './graphLayoutStorage';

/** Disconnected mentions are not relationships. Keep them available outside the network. */
export function partitionRelationships(graph: GraphPayload) {
  const ids = new Set(graph.entities.map(e => e.id));
  const relations = graph.relations.filter(r => r.source_entity_id !== r.target_entity_id && ids.has(r.source_entity_id) && ids.has(r.target_entity_id));
  const linked = new Set(relations.flatMap(r => [r.source_entity_id, r.target_entity_id]));
  return { network: {...graph, entities: graph.entities.filter(e => linked.has(e.id)), relations},
    unlinked: graph.entities.filter(e => !linked.has(e.id)) };
}

/** Group parallel claims between the same two entities for a readable overview. */
export function aggregateRelationshipPairs(relations: RelationEdge[]) {
  const groups = new Map<string, RelationEdge[]>();
  for (const relation of relations) {
    const key = [relation.source_entity_id, relation.target_entity_id].sort((a, b) => a - b).join(':');
    groups.set(key, [...(groups.get(key) ?? []), relation]);
  }
  return [...groups.entries()].map(([pairKey, members]) => ({ pairKey, members }));
}

/** Pick a deterministic, evidence-weighted spanning forest for the overview.
 * The forest is only a visual backbone: every extracted relation remains in
 * the payload and can still be inspected in the evidence rail. Keeping one
 * representative per pair prevents dense cycles from overpowering the
 * story's main connective path. */
export function relationshipBackboneIds(entities: EntityNode[], relations: RelationEdge[]) {
  const entityIds = new Set(entities.map((entity) => entity.id));
  const groups = aggregateRelationshipPairs(relations).filter(({ members }) => members.every((relation) =>
    relation.source_entity_id !== relation.target_entity_id &&
    entityIds.has(relation.source_entity_id) && entityIds.has(relation.target_entity_id),
  ));
  const representative = groups.map(({ members }) => [...members].sort((left, right) => {
    const score = (candidate: RelationEdge) =>
      Number(candidate.confidence ?? 0) * 10 + (candidate.evidence_chunk_ids?.length ?? 0) * 4 + (candidate.claims?.length ?? 0) * 3 + (candidate.is_weak ? 0 : 1);
    return score(right) - score(left) || left.id - right.id;
  })[0]).filter((relation): relation is RelationEdge => Boolean(relation));
  const parent = new Map<number, number>([...entityIds].map((id) => [id, id]));
  const find = (id: number): number => {
    const current = parent.get(id) ?? id;
    if (current === id) return id;
    const root = find(current);
    parent.set(id, root);
    return root;
  };
  const union = (left: number, right: number) => {
    const leftRoot = find(left); const rightRoot = find(right);
    if (leftRoot === rightRoot) return false;
    parent.set(rightRoot, leftRoot);
    return true;
  };
  const score = (candidate: RelationEdge) =>
    Number(candidate.confidence ?? 0) * 10 + (candidate.evidence_chunk_ids?.length ?? 0) * 4 + (candidate.claims?.length ?? 0) * 3 + (candidate.is_weak ? 0 : 1);
  const pairKey = (candidate: RelationEdge) => [candidate.source_entity_id, candidate.target_entity_id].sort((a, b) => a - b).join(':');
  const sorted = [...representative].sort((left, right) =>
    score(right) - score(left) || pairKey(left).localeCompare(pairKey(right), 'en') || left.id - right.id,
  );
  return new Set(sorted.filter((relation) => union(relation.source_entity_id, relation.target_entity_id)).map((relation) => relation.id));
}

/** Add non-persisted ghost entities for relations whose extracted endpoint is
 * missing from the visible entity set. This keeps diagnostics visible on the
 * map while making it impossible to accidentally treat a ghost as an author
 * confirmed entity. */
export function appendDanglingGhosts(graph: GraphPayload, visible: GraphPayload): GraphPayload {
  const entityIds = new Set(visible.entities.map(entity => entity.id));
  const dangling = graph.relations.filter(relation =>
    !entityIds.has(relation.source_entity_id) || !entityIds.has(relation.target_entity_id),
  );
  if (!dangling.length) return visible;
  const ghosts = new Map<number, EntityNode>();
  for (const relation of dangling) for (const id of [relation.source_entity_id, relation.target_entity_id]) {
    if (entityIds.has(id) || ghosts.has(id)) continue;
    ghosts.set(id, { id, project_id: graph.entities[0]?.project_id ?? 0, type: 'event',
      name: `미확인 대상 #${id}`, aliases: [], summary: '관계 끝점은 찾았지만 대상 엔티티가 등록되지 않았습니다.',
      first_seen_document_id: null, mention_count: 0, document_ids: [], document_count: 0,
      last_seen_document_id: null, appearance_state: 'dormant', visual_weight: 0.25 });
  }
  return { ...visible, entities: [...visible.entities, ...ghosts.values()], relations: [...visible.relations, ...dangling] };
}

/** Deterministic layered layout: a high-degree anchor starts the first layer
 * and relationship hops flow downward. Repeated barycenter sweeps reduce edge
 * crossings while keeping the result stable between runs.
 */
export function relationshipPositions(graph: GraphPayload): Map<number, GraphPosition> {
  const adjacency = new Map(graph.entities.map(e => [e.id, new Set<number>()]));
  for (const r of graph.relations) {
    if (r.source_entity_id === r.target_entity_id || !adjacency.has(r.source_entity_id) || !adjacency.has(r.target_entity_id)) continue;
    adjacency.get(r.source_entity_id)!.add(r.target_entity_id);
    adjacency.get(r.target_entity_id)!.add(r.source_entity_id);
  }
  const remaining = new Set([...adjacency.keys()].sort((a,b)=>a-b));
  const components: number[][] = [];
  while (remaining.size) {
    const queue = [remaining.values().next().value!]; remaining.delete(queue[0]);
    for (let i=0;i<queue.length;i++) for (const id of [...adjacency.get(queue[i])!].sort((a,b)=>a-b)) if (remaining.delete(id)) queue.push(id);
    components.push(queue);
  }
  components.sort((a,b)=>b.length-a.length || a[0]-b[0]);
  const result = new Map<number, GraphPosition>();
  // Pack connected components into a balanced grid. A single horizontal row
  // makes “전체 관계” shrink into unreadable thumbnails as soon as a project
  // has several independent subgraphs.
  const componentLayouts = components.map((ids) => {
    const degree = (id:number) => adjacency.get(id)!.size;
    const root = [...ids].sort((a,b)=>degree(b)-degree(a)||a-b)[0];
    const levels = new Map<number,number>([[root,0]]);
    const queue=[root];
    for(let i=0;i<queue.length;i++) for(const next of [...adjacency.get(queue[i])!].sort((a,b)=>a-b)) if(!levels.has(next)){levels.set(next,levels.get(queue[i])!+1);queue.push(next);}
    const byLevel = new Map<number,number[]>();
    for(const id of ids) { const level=levels.get(id)??0; byLevel.set(level,[...(byLevel.get(level)??[]),id]); }
    const coordinates = new Map<number,{x:number;y:number}>();
    // Use a layered (Sugiyama-style) composition instead of concentric rings.
    // Writers can follow a relationship from the high-degree anchor downward,
    // while sibling nodes stay in a stable order near their shared parents.
    const orderedLevels = new Map<number, number[]>(
      [...byLevel.entries()].map(([level, levelIds]) => [level, [...levelIds].sort((a, b) => degree(b) - degree(a) || a - b)]),
    );
    const layerKeys = [...orderedLevels.keys()].sort((a, b) => a - b);
    const indexOf = (level: number) => new Map((orderedLevels.get(level) ?? []).map((id, index) => [id, index]));
    const barycenter = (id: number, neighbouringLevel: number) => {
      const positions = indexOf(neighbouringLevel);
      const neighbours = [...(adjacency.get(id) ?? [])]
        .map((neighbour) => positions.get(neighbour))
        .filter((index): index is number => index !== undefined);
      return neighbours.length ? neighbours.reduce((sum, index) => sum + index, 0) / neighbours.length : Number.POSITIVE_INFINITY;
    };
    // Four alternating sweeps are enough to settle sibling order for the
    // story-sized graphs we render, without introducing a force simulation's
    // non-determinism or expensive animation.
    for (let sweep = 0; sweep < 4; sweep += 1) {
      for (const level of layerKeys.slice(1)) {
        const previous = level - 1;
        orderedLevels.set(level, [...(orderedLevels.get(level) ?? [])].sort((left, right) =>
          barycenter(left, previous) - barycenter(right, previous) || degree(right) - degree(left) || left - right));
      }
      for (const level of [...layerKeys].reverse().slice(1)) {
        const next = level + 1;
        orderedLevels.set(level, [...(orderedLevels.get(level) ?? [])].sort((left, right) =>
          barycenter(left, next) - barycenter(right, next) || degree(right) - degree(left) || left - right));
      }
    }
    // Keep story-sized maps compact enough that fit() does not reduce the
    // entire network to a thumbnail. The node cards are ~90–120px wide, so
    // these gaps leave room for labels while preserving the main path.
    const spacing = ids.length > 36 ? 195 : ids.length > 20 ? 198 : 205;
    const maxLevel = Math.max(...layerKeys, 0);
    const wrapDeepChain = maxLevel > 8 && ids.length > 18;
    let levelY = 0;
    for (const level of layerKeys) {
      const ordered = orderedLevels.get(level) ?? [];
      if (wrapDeepChain && ordered.length === 1) {
        // Long chains otherwise become a very tall strip and Cytoscape has to
        // zoom the entire story down to a thumbnail. Fold every six hops into
        // a new row while preserving deterministic traversal order.
        const column = level % 6;
        const row = Math.floor(level / 6);
        coordinates.set(ordered[0], { x: column * spacing, y: row * 180 });
        continue;
      }
      // Wide BFS layers are the main source of the unreadable "horizontal
      // strip" in 전체 관계. Wrap siblings into balanced rows so the map
      // keeps a usable aspect ratio and labels have room to breathe.
      const perRow = ordered.length > 12 ? 7 : ordered.length > 7 ? 6 : ordered.length;
      const rowCount = Math.max(1, Math.ceil(ordered.length / Math.max(1, perRow)));
      for (let row = 0; row < rowCount; row += 1) {
        const rowItems = ordered.slice(row * perRow, (row + 1) * perRow);
        const width = (rowItems.length - 1) * spacing;
        rowItems.forEach((id, index) => coordinates.set(id, {
          x: index * spacing - width / 2,
          y: levelY + row * 164,
        }));
      }
      levelY += rowCount * 164 + 72;
    }
    const values=[...coordinates.values()];
    const minX=Math.min(...values.map(p=>p.x)),minY=Math.min(...values.map(p=>p.y));
    const maxX=Math.max(...values.map(p=>p.x)),maxY=Math.max(...values.map(p=>p.y));
    return { coordinates, minX, minY, width:maxX-minX+180, height:maxY-minY+164 };
  });
  const columns = Math.max(1, Math.ceil(Math.sqrt(componentLayouts.length)));
  const rows = Math.ceil(componentLayouts.length / columns);
  const columnWidths = Array.from({length:columns},(_,column)=>Math.max(...componentLayouts.filter((_,index)=>index%columns===column).map(layout=>layout.width), 0));
  const rowHeights = Array.from({length:rows},(_,row)=>Math.max(...componentLayouts.slice(row*columns,(row+1)*columns).map(layout=>layout.height), 0));
  const totalWidth = columnWidths.reduce((sum,width)=>sum+width,0) + (columns-1)*120;
  const totalHeight = rowHeights.reduce((sum,height)=>sum+height,0) + (rows-1)*120;
  let rowY = -totalHeight/2;
  componentLayouts.forEach((layout,index)=>{
    const row=Math.floor(index/columns), column=index%columns;
    const rowTop = rowY + rowHeights.slice(0,row).reduce((sum,height)=>sum+height,0) + row*120;
    const columnLeft = -totalWidth/2 + columnWidths.slice(0,column).reduce((sum,width)=>sum+width,0) + column*120;
    for(const [id,point] of layout.coordinates) result.set(id,{x:point.x-layout.minX+columnLeft,y:point.y-layout.minY+rowTop});
  });
  // A ring can still place two cards on nearly the same diagonal. Resolve
  // those rare collisions deterministically before Cytoscape fits the map.
  const placed: GraphPosition[] = [];
  for (const [id, original] of result) {
    const point = { ...original };
    let guard = 0;
    // Never create an unbounded vertical chain while resolving collisions.
    // The previous one-axis walk could make a 20-node graph thousands of
    // pixels tall, causing Cytoscape.fit() to shrink the useful network.
    while (placed.some(other => Math.abs(point.x - other.x) < 190 && Math.abs(point.y - other.y) < 123) && guard < 8) {
      const step = guard + 1;
      const column = Math.ceil(step / 2);
      point.x += (step % 2 ? 1 : -1) * column * 210;
      point.y += (step % 2 ? 1 : -1) * Math.floor((step - 1) / 2) * 132;
      guard += 1;
    }
    result.set(id, point);
    placed.push(point);
  }
  return result;
}
