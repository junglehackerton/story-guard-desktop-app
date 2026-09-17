import type { IssueStatus } from '../lib/types';
import { judgmentLabel } from '../lib/reviewGraph';
import { sample } from './data';
import { guideIssueId, guideSources } from './guide';

type Props = {
  status: IssueStatus;
  onSave: (id: number, status: IssueStatus) => Promise<boolean>;
  onSource: (id: number, quote: string) => void;
  onGraph: () => void;
  onReview: () => void;
  onClues: () => void;
  onAnalyze: () => void;
  onTutorial: () => void;
};

export function DemoGuide({status,onSave,onSource,onGraph,onReview,onClues,onAnalyze,onTutorial}: Props) {
  function excerpt(index: number) {
    const source = guideSources[index];
    const chunk = sample.chunks.find(c => c.id === source.chunkId)!;
    return <article className="demo-excerpt" key={source.chunkId}>
      <h3>{source.label}</h3>
      {source.quotes.map(quote => <blockquote key={quote}>{quote}</blockquote>)}
      <button className="text-action" onClick={() => onSource(chunk.document_id, source.quotes[0])}>{index === 0 ? '3화' : '5화'} 전체 원문에서 확인</button>
    </article>;
  }
  return <div className="demo-guide">
    <section className="surface demo-guide-intro">
      <span className="badge">첫 체험 · 저장된 실제 분석 결과</span>
      <h2>잘라 버린 열쇠가 다시 사용된다면?</h2>
      <p>윤해주는 철거 직전의 호텔에서 비밀을 추적합니다. 스토리 가드가 찾은 후보 하나를 원문과 비교하고, 작가의 입장에서 판단해 보세요.</p>
      <ol className="demo-steps" aria-label="체험 순서"><li>두 회차 비교</li><li>작가 판단</li><li>관계·단서 탐색</li></ol><button className="text-action demo-reopen-tutorial" onClick={onTutorial}>체험 안내 다시 보기</button>
    </section>
    <section className="surface demo-guide-evidence" aria-labelledby="guide-evidence-title">
      <h2 id="guide-evidence-title">1. 앞뒤 회차의 근거를 비교하세요</h2>
      <div className="demo-evidence-pair"><div>{excerpt(0)}</div><div>{excerpt(1)}<details><summary>실제로 사용한 장면도 확인하기</summary>{excerpt(2)}</details></div></div>
    </section>
    <section className="surface demo-guide-judgment" aria-labelledby="guide-judgment-title">
      <h2 id="guide-judgment-title">2. 이 설정은 수정이 필요할까요?</h2>
      <p>AI는 수리·대체 설명을 찾지 못해 충돌 후보로 제시했습니다. 다른 회차의 설명이나 작가의 의도가 있다면 문제가 아닐 수 있습니다.</p>
      <div className="demo-judgment-buttons" role="group" aria-label="열쇠 사례에 대한 작가 판단">
        {([['accepted','문제 있음'],['ignored','문제 아님'],['deferred','판단 보류']] as const).map(([value,label]) => <button key={value} aria-pressed={status===value} onClick={() => void onSave(guideIssueId,value)}>{label}</button>)}
      </div>
      <p role="status">{status==='open' ? '정답 맞히기가 아닙니다. 근거를 읽고 판단을 남겨 보세요.' : `내 판단: ${judgmentLabel[status]}. 검토 결과에도 반영했습니다. 판단은 언제든 바꿀 수 있습니다.`}</p>
      {status!=='open' && <button className="text-action" onClick={() => void onSave(guideIssueId,'open')}>확인 대기로 되돌리기</button>}
    </section>
    <section className="surface demo-guide-next">
      <h2>3. 열쇠 사례의 연결을 확인하세요</h2>
      <p>앞에서 비교한 열쇠가 어떤 인물·아이템·장소와 이어지는지 관계 지도에서 원문 근거와 함께 살펴보세요.</p>
      <div className="demo-next-actions"><button className="primary" onClick={onGraph}>열쇠 사례의 관계 지도 보기</button></div>
      <div className="demo-live-invitation"><div><h3>다른 문장을 AI로 확인해 보려면</h3><p>열쇠 사례의 기존 원문 범위를 기준으로 새 문장을 비교합니다. 이 기능은 실제 AI 요청과 하루 이용 한도를 사용합니다.</p></div><button onClick={onAnalyze}>새 문장으로 실시간 분석</button></div>
    </section>
  </div>;
}
