import { expect, it } from 'vitest';
import { aggregateRelationshipPairs, appendDanglingGhosts, partitionRelationships, relationshipBackboneIds, relationshipPositions } from './relationshipLayout';
import type { GraphPayload } from './types';
const fixture=(count:number,edges:number[][])=>({entities:Array.from({length:count},(_,id)=>({id})),relations:edges.map(([source_entity_id,target_entity_id],id)=>({id,source_entity_id,target_entity_id}))} as GraphPayload);
it('does not let 35 unrelated mentions shrink a four-node relationship network',()=>{
  const g=fixture(39,[[0,1],[1,2],[2,3],[2,3]]);
  const {network,unlinked}=partitionRelationships(g);
  expect(network.entities).toHaveLength(4);expect(network.relations).toHaveLength(4);expect(unlinked).toHaveLength(35);
  expect(relationshipPositions(network)).toEqual(relationshipPositions(partitionRelationships(fixture(4,[[0,1],[1,2],[2,3],[2,3]])).network));
});
it('keeps cards separate for chain, hub and dense connected graphs',()=>{
  for(const edges of [Array.from({length:49},(_,i)=>[i,i+1]),Array.from({length:49},(_,i)=>[0,i+1]),Array.from({length:50},(_,i)=>[i,(i+7)%50])]){
    const points=[...relationshipPositions(fixture(50,edges)).values()];
    for(let a=0;a<points.length;a++)for(let b=a+1;b<points.length;b++)expect(Math.abs(points[a].x-points[b].x)>=190 || Math.abs(points[a].y-points[b].y)>=123).toBe(true);
  }
});
it('keeps a normal story component compact enough for readable fit',()=>{
  const g=fixture(8,[[0,1],[0,2],[0,3],[1,4],[1,5],[2,6],[2,7]]);
  const points=[...relationshipPositions(g).values()];
  const width=Math.max(...points.map(point=>point.x))-Math.min(...points.map(point=>point.x));
  const height=Math.max(...points.map(point=>point.y))-Math.min(...points.map(point=>point.y));
  expect(width).toBeLessThan(1000);
  expect(height).toBeLessThan(1000);
});
it('folds a deep chain into a readable grid instead of a thumbnail-height strip',()=>{
  const g=fixture(30,Array.from({length:29},(_,i)=>[i,i+1]));
  const points=[...relationshipPositions(g).values()];
  const height=Math.max(...points.map(point=>point.y))-Math.min(...points.map(point=>point.y));
  expect(height).toBeLessThan(1200);
});
it('is deterministic across input ordering and ignores dangling/self edges',()=>{
  const g=fixture(5,[[0,1],[1,2],[9,2],[4,4]]);
  expect(partitionRelationships(g).network.relations).toHaveLength(2);
  expect(relationshipPositions(g)).toEqual(relationshipPositions({...g,entities:[...g.entities].reverse(),relations:[...g.relations].reverse()}));
});
it('groups parallel claims regardless of direction and preserves members',()=>{
  const g=fixture(3,[[0,1],[1,0],[1,2]]);
  expect(aggregateRelationshipPairs(g.relations).map(group=>[group.pairKey,group.members.length])).toEqual([['0:1',2],['1:2',1]]);
});
it('keeps a missing relationship endpoint visible as a non-persisted ghost',()=>{
  const source=fixture(2,[[0,1],[0,9]]);
  const visible={...source,relations:[source.relations[0]]};
  const canvas=appendDanglingGhosts(source,visible);
  expect(canvas.entities.map(entity=>entity.name)).toContain('미확인 대상 #9');
  expect(canvas.relations).toHaveLength(2);
  expect(visible.entities).toHaveLength(2);
});
it('chooses an evidence-weighted spanning backbone without hiding cycle claims',()=>{
  const g=fixture(4,[[0,1],[1,2],[2,3],[0,3],[0,2]]);
  const ids=relationshipBackboneIds(g.entities,g.relations);
  expect(ids).toHaveLength(3);
  expect([...ids]).toEqual([0,4,3]);
  expect(g.relations).toHaveLength(5);
});
