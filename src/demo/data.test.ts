import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { sample } from './data';
import { WorkbenchNav, ManuscriptsPage } from '../components/Workbench';

describe('public demo snapshot',()=>{
 it('contains exactly the public sample and source-backed evidence',()=>{
  expect(sample.documents).toHaveLength(10);
  expect(sample.graph.issues).toHaveLength(3);
  const documents=new Map(sample.documents.map(d=>[d.id,d]));
  const chunks=new Map(sample.chunks.map(c=>[c.id,c]));
  for(const c of sample.chunks) expect(documents.get(c.document_id)?.content).toContain(c.text);
  for(const i of sample.graph.issues) for(const id of i.evidence_chunk_ids)expect(chunks.has(id)).toBe(true);
  for(const r of sample.graph.relations) for(const claim of r.claims||[])for(const q of claim.quotes)expect(documents.get(q.document_id)?.content).toContain(q.quote);
  expect(JSON.stringify(sample)).not.toMatch(/\/Users\/|access_token|refresh_token|api_key/);
 });
 it('keeps desktop navigation but labels demo storage honestly',()=>{
  const html=renderToStaticMarkup(createElement(WorkbenchNav,{demo:true,page:'analysis',onPage:()=>{},project:sample.project,projects:[sample.project],onProject:()=>{}}));
  expect(html).toContain('원고·설정');expect(html).toContain('관계 지도');expect(html).toContain('공개 샘플');expect(html).not.toContain('원고는 이 기기에 저장됩니다');
 });
 it('removes write controls only in read-only manuscript mode',()=>{
  const props={documents:sample.documents,settings:[],loading:false,onImport:()=>{},onDelete:()=>{},onReplace:()=>{},onEdit:async()=>false,onAnalyze:()=>{},onCreateSetting:async()=>false,onUpdateSetting:async()=>false,onDeleteSetting:()=>{}};
  const html=renderToStaticMarkup(createElement(ManuscriptsPage,{...props,readOnly:true}));
  expect(html).not.toContain('원문 편집');expect(html).not.toContain('수정본 파일 교체');expect(html).not.toContain('원고 삭제');
  const desktop=renderToStaticMarkup(createElement(ManuscriptsPage,props));expect(desktop).toContain('원문 편집');
 });
});
