import { expect, it } from 'vitest';
import { relatedRelations, relationJudgments } from './reviewGraph';
import type { RelationEdge, ContinuityIssue } from './types';
const relations = [
 {id:1,evidence_chunk_ids:[10],claims:[]},
 {id:2,evidence_chunk_ids:[20],claims:[]},
 {id:3,evidence_chunk_ids:[10,20],claims:[]},
 {id:4,evidence_chunk_ids:[],claims:[{quotes:[{chunk_id:30}]}]},
] as unknown as RelationEdge[];
it('opens each evidence passage independently and ranks shared evidence first', () => {
 expect(relatedRelations(relations,[10,20]).map(r=>r.id)).toEqual([3,1,2]);
 expect(relatedRelations(relations,[20]).map(r=>r.id)).toEqual([2,3]);
 expect(relatedRelations(relations,[30]).map(r=>r.id)).toEqual([4]);
 expect(relatedRelations(relations,[99])).toEqual([]);
});
it('reflects changed judgments without reanalysis and excludes unrelated evidence', () => {
 for (const status of ['open','accepted','ignored','deferred'] as const) {
  const issues = [{id:1,status,evidence_chunk_ids:[20]}] as ContinuityIssue[];
  expect(relationJudgments(relations[1],issues)[0].status).toBe(status);
  expect(relationJudgments(relations[0],issues)).toEqual([]);
 }
});
