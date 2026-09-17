import { afterEach, describe, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import DemoPage from '../DemoPage';
import { sample, loadJudgments, loadClueJudgments } from './data';
import { guideAvailable, guideIssueId, guideSources, evidenceChapters } from './guide';

afterEach(()=>vi.unstubAllGlobals());
describe('stable guided demo',()=>{
 it('uses the actual issue evidence and verbatim chapter 3 and 5 excerpts',()=>{
  expect(guideAvailable()).toBe(true);
  expect(sample.graph.issues.find(i=>i.id===guideIssueId)?.evidence_chunk_ids).toEqual(expect.arrayContaining(guideSources.map(s=>s.chunkId)));
  expect(guideSources.map(s=>sample.documents.find(d=>d.id===sample.chunks.find(c=>c.id===s.chunkId)?.document_id)?.chapter_index)).toEqual([2,4,4]);
 });
 it('does not show stale curated evidence if the snapshot changes',()=>{
  const chunk=sample.chunks.find(c=>c.id===guideSources[0].chunkId)!;
  const previous=chunk.text;
  try {chunk.text='changed';expect(guideAvailable()).toBe(false);} finally {chunk.text=previous;}
 });
 it('opens the introduction without storage or a live AI connection',()=>{
  vi.stubGlobal('localStorage',{getItem:()=>{throw new Error('blocked');}});
  const html=renderToStaticMarkup(createElement(DemoPage));
  expect(html).toContain('하나의 설정이,');
  expect(html).toContain('스토리 가드는 원문 근거와 함께');
  expect(html).toContain('핵심 기능 체험하기');
  expect(html).toContain('원문, 검토, 관계를');
  expect(html).toContain('검토 결과');
  expect(html).toContain('관계 지도');
  expect(html).not.toContain('DEMO NOTE');
  expect(loadJudgments()).toEqual({});expect(loadClueJudgments()).toEqual({});
 });
 it('ignores corrupted and unrelated browser judgments',()=>{
  vi.stubGlobal('localStorage',{getItem:()=>JSON.stringify({'70':'accepted','999999':'ignored','1182':'resolved','1204':'bad'})});
  expect(loadJudgments()).toEqual({70:'accepted'});
  expect(loadClueJudgments()).toEqual({1182:'resolved'});
 });
 it('only links published documents for clue evidence',()=>{
  for(const e of sample.graph.entities.filter(e=>e.type==='foreshadowing')) {
   const docs=evidenceChapters(e.id);
   expect(new Set(docs.map(d=>d.id)).size).toBe(docs.length);
   for(const d of docs) expect(sample.documents).toContain(d);
  }
 });
});
