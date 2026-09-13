import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { DocumentPicker } from './DocumentPicker';
import type { StoryDocument } from '../lib/types';

it('distinguishes modified drafts from drafts that have never been analyzed', () => {
 const documents = [{id:1,title:'신규',chapter_index:0,analysis_status:'pending'}, {id:2,title:'수정본',chapter_index:1,analysis_status:'stale'}] as StoryDocument[];
 const html = renderToStaticMarkup(<DocumentPicker documents={documents} onSelect={()=>{}}/>);
 expect(html).toContain('아직 분석하지 않음');
 expect(html).toContain('수정 후 재분석 필요');
});

it('bounds the initial rendered list for a 500-episode work', () => {
 const documents = Array.from({length:500},(_,i)=>({id:i+1,title:`회차제목${i+1}`,chapter_index:i,analysis_status:'pending'})) as StoryDocument[];
 const html = renderToStaticMarkup(<DocumentPicker documents={documents} onSelect={()=>{}}/>);
 expect(html.match(/화 · /g)).toHaveLength(12);
 expect(html).toContain('원고 다음 페이지');
 expect(html).not.toContain('회차제목500');
});
