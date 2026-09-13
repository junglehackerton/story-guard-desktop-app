import {expect,it} from 'vitest';
import {relationshipAccount} from './RelationStory';
import type {GraphPayload,RelationEdge} from '../lib/types';
const edge=(id:number,source:number,target:number,chapter:number,basis:'explicit'|'inferred'='explicit')=>({id,source_entity_id:source,target_entity_id:target,type:'보호',claims:[{explanation:'도윤이 아린을 보호했다.',basis,quotes:[{chunk_id:id,document_id:id,chapter_index:chapter,quote:'보호했다.'}]}]} as RelationEdge);
it('preserves reverse direction and inference while sorting manuscript chapters',()=>{
 const a=edge(1,1,2,5),b=edge(2,2,1,0,'inferred'),other=edge(3,2,3,1);
 const account=relationshipAccount(a,{relations:[a,other,b]} as GraphPayload);
 expect(account.map(x=>x.relation.id)).toEqual([2,1]);
 expect(account[0].claim.basis).toBe('inferred');
 expect(account[0].relation.source_entity_id).toBe(2);
});
it('does not fabricate explanations for legacy relations',()=>{
 const a={...edge(1,1,2,0),claims:undefined};
 expect(relationshipAccount(a,{relations:[a]} as GraphPayload)).toEqual([]);
});
