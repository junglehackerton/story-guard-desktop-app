import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { ReviewPage } from './Workbench';
import type { GraphPayload, StoryDocument } from '../lib/types';

const graph = { entities: [], relations: [], issues: [], changes: [] } as unknown as GraphPayload;
const props = { graph, documents: [] as StoryDocument[], evidence: {}, history: [], onStatus: () => {}, onGraph: () => {}, onOpenDocument: () => {}, onAnalysis: () => {} };

it('offers existing judgments instead of reanalysis when every candidate was reviewed', () => {
 const html = renderToStaticMarkup(<ReviewPage {...props} graph={{...graph, issues:[{id:1,status:'deferred',title:'확인할 규칙',description:'작가 판단 대기'}] as GraphPayload['issues']}}/>);
 expect(html).toContain('확인 대기 후보를 모두 검토했습니다');
 expect(html).toContain('작가 판단 보기');
 expect(html).not.toContain('원고를 다시 분석해 보세요');
});

it('directs imported drafts with no extraction yet to analysis, not back to import', () => {
 const html = renderToStaticMarkup(<ReviewPage {...props} documents={[{id:1,analysis_status:'pending'} as StoryDocument]}/>);
 expect(html).toContain('분석이 필요한 원고가 있습니다');
 expect(html).toContain('분석 설정으로 이동');
});

it('never presents no candidates as proof of a successful analysis', () => {
 const html = renderToStaticMarkup(<ReviewPage {...props} documents={[{id:1,analysis_status:'analyzed'} as StoryDocument]}/>);
 expect(html).toContain('설정 오류가 없다는 뜻은 아닙니다');
 expect(html).toContain('실패 내역');
});
