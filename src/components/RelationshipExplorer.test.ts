import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { RelationshipExplorer } from './RelationshipExplorer';
import type { GraphPayload, EvidenceChunk } from '../lib/types';

it('shows persisted unresolved targets with the relationship and its explanation', () => {
  const graph = {
    entities: [
      { id: 1, name: '해주', type: 'character', aliases: [] },
      { id: 2, name: '미확인 대상 #window (missing)', type: 'event', is_unresolved: true,
        summary: 'AI 추출 누락 확인 필요', aliases: [] },
    ],
    relations: [{ id: 3, source_entity_id: 1, target_entity_id: 2, type: '소유함',
      display_label: '소유함', has_unresolved_endpoint: true, evidence_chunk_ids: [42],
      confidence: 0.7, is_weak: false, claims: [{ explanation: '연결 대상 확인이 필요합니다.',
        basis: 'inferred', quotes: [{ chunk_id: 42, document_id: 4, chapter_index: 0, quote: '해주가 열쇠를 쥐었다.' }] }] }],
  } as unknown as GraphPayload;
  const html = renderToStaticMarkup(createElement(RelationshipExplorer, {
    projectId: 1, graph, selectedEntityId: null, selectedRelationId: 3, onSelectEntity: () => {},
  }));
  expect(html).toContain('미확인 대상');
  expect(html).not.toContain('미확인 대상 #window');
  expect(html).toContain('대상 연결 미확인');
  expect(html).toContain('연결 대상 확인이 필요합니다.');
  expect(html).toContain('작가의 설정 오류로 확정하지 않습니다');
  expect(html).toContain('문제 점검 <b>1</b>');
  expect(html).toContain('원문에서 근거 보기');
});

it('shows the review judgment, source comparison and selected relation together', () => {
 const graph = {
  entities:[{id:1,name:'해주',type:'character'},{id:2,name:'열쇠',type:'item'}],
  relations:[{id:3,source_entity_id:1,target_entity_id:2,type:'절단함',evidence_chunk_ids:[10],confidence:0.7,claims:[]}],
  issues:[{id:9,title:'열쇠 상태 충돌',description:'파손 후 재사용',status:'accepted',evidence_chunk_ids:[10,20]}],
 } as unknown as GraphPayload;
 const html = renderToStaticMarkup(createElement(RelationshipExplorer, {
  projectId:1,graph,selectedEntityId:null,selectedRelationId:3,onSelectEntity:()=>{},
  reviewFocus:{issueId:9},reviewEvidence:[{id:10,document_id:1,text:'열쇠를 잘랐다.'},{id:20,document_id:2,text:'온전한 열쇠로 열었다.'}] as unknown as EvidenceChunk[],
 }));
 expect(html).toContain('열쇠 상태 충돌');
 expect(html).toContain('관련 검토 · 문제 있음');
 expect(html).toContain('선택한 관계');
 expect(html).toContain('열쇠를 잘랐다.');
 expect(html).toContain('온전한 열쇠로 열었다.');
});
