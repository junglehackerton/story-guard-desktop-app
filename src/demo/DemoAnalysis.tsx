import { useEffect, useRef, useState } from 'react';
import { sample } from './data';
export type LiveAnalysis = {text: string; summary: string; verdict: string; evidence: {id:number;document_id:number;text:string}[]; new_relations?: {source:string;source_type?:string;target:string;target_type?:string;label:string}[]; remaining: number; resolved?: boolean};
const localDesktop = typeof window !== 'undefined' && (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost');
const base = (import.meta.env.VITE_DEMO_API_URL || (localDesktop ? 'http://127.0.0.1:18765' : '')).replace(/\/$/, '');
const apiPath = localDesktop && !import.meta.env.VITE_DEMO_API_URL ? '/demo' : '/api/demo';
const repairedSentence = '그리고 서우가 미리 건네준 예비 열쇠를 꺼내 열여덟 번 사물함을 열었다.';
const staticDemo = import.meta.env.VITE_DEMO_STATIC === 'true';
export function DemoAnalysis({active=true,onSource,onGraph,onReview,onResult}: {active?:boolean;onSource:(id:number,quote?:string)=>void;onGraph:()=>void;onReview:()=>void;onResult:(result:LiveAnalysis|null)=>void}) {
  const chapter = 4;
  const [text,setText] = useState(repairedSentence);
  const [remaining,setRemaining] = useState<number | null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [availability,setAvailability] = useState('AI 연결 상태를 확인하는 중입니다.');
  const [ready,setReady] = useState(false);
  const [result,setResult] = useState<LiveAnalysis | null>(null);
  const [overrideDraft,setOverrideDraft] = useState<Record<number,string>>({});
  const [overrides,setOverrides] = useState<Record<number,string>>({});
  const textArea = useRef<HTMLTextAreaElement | null>(null);
  const pending = useRef(false);
  const request = useRef<{key:string;id:string}>();
  const abort = useRef<AbortController | null>(null);
  const statusLoaded = useRef(false);
  const lastVerdict = useRef<string | null>(null);
  useEffect(()=>{
    if(staticDemo) {
      setReady(false);
      setAvailability('정적 미리보기입니다. 서버 연결 없이 준비된 샘플 결과를 탐색할 수 있습니다.');
      return;
    }
    if(!active) {
      abort.current?.abort();
      abort.current=null;
      pending.current=false;
      setText(repairedSentence);
      setResult(null);
      setOverrideDraft({});
      setOverrides({});
      setError('');
      lastVerdict.current=null;
      return;
    }
    if(statusLoaded.current) return;
    const controller = new AbortController();
    fetch(`${base}${apiPath}/status`, {credentials:'include',signal:controller.signal}).then(async r=>{
      if(!r.ok) throw new Error();
      const s=await r.json();statusLoaded.current=true;setRemaining(s.remaining);setReady(s.ready);setAvailability(s.message);
    }).catch(()=>{if(!controller.signal.aborted)setAvailability('AI 검토 서버가 연결되지 않았습니다. 준비된 분석 결과는 모두 탐색할 수 있습니다.');});
    return ()=>controller.abort();
  },[active]);
  useEffect(()=>()=>{
    // A live result is intentionally memory-only. Leaving the demo aborts the
    // browser request and drops the result/query state on unmount.
    abort.current?.abort();
    abort.current=null;
    pending.current=false;
  },[]);
  async function analyze(nextOverrides = overrides) {
    if(pending.current || !text.trim() || !ready || remaining===0) return;
    pending.current=true;setBusy(true);setError('');setResult(null);
    const key=`${chapter}:${text.trim()}:${JSON.stringify(nextOverrides)}`;
    if(request.current?.key!==key)request.current={key,id:crypto.randomUUID()};
    const controller=new AbortController();
    abort.current=controller;
    try {
      const response=await fetch(`${base}${apiPath}/analyze`,{method:'POST',credentials:'include',signal:controller.signal,headers:{'content-type':'application/json'},body:JSON.stringify({text:text.trim(),end_chapter:chapter,version:sample.version,request_id:request.current.id,overrides:Object.entries(nextOverrides).map(([id,value])=>({id:Number(id),text:value}))})});
      const data=await response.json();
      if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.');
      const live={...data,text:text.trim(),resolved:lastVerdict.current==='conflict' && data.verdict==='clear'} as LiveAnalysis;
      lastVerdict.current=data.verdict;
      setResult(live);setOverrideDraft(Object.fromEntries(live.evidence.map(e=>[e.id,e.text])));setRemaining(data.remaining);onResult(live);request.current=undefined;
    } catch(e) {
      if (!(e instanceof DOMException && e.name==='AbortError')) setError(e instanceof Error ? e.message : '분석 요청에 실패했습니다.');
    }
    finally {if(abort.current===controller)abort.current=null;pending.current=false;setBusy(false);}
  }
  return <div className="demo-analysis-grid"><section className="surface"><h2>분석 대상</h2><div className="soft-card"><h3>{sample.project.title}</h3><p>열쇠 사례 원고 · {sample.documents.length}화</p><p>앞서 확인한 열쇠 장면을 포함한 공개 샘플입니다. 수정한 문장은 이 원고의 설정과 비교합니다.</p></div><h3>준비된 분석 결과</h3><p className="muted">{sample.provenance}</p><div className="demo-result-links"><button onClick={onReview}>검토 결과 · {sample.graph.issues.length}개</button><button onClick={onGraph}>관계 지도 · {sample.graph.relations.length}개</button><button onClick={()=>onSource(sample.documents[0].id)}>원고 읽기 · 10화</button></div></section>
    <section className="surface"><span className="badge">실시간 AI 분석 · 입력 후 요청</span><h2>5화 문장을 수정해 다시 분석</h2><p>앞서 확인한 5화의 문제 문장을 직접 고친 뒤, 3화의 열쇠 근거와 비교해 결과가 어떻게 달라지는지 확인합니다.</p><div className="demo-analysis-context"><strong>수정할 장면 · 5화</strong><span>3화에서 절단된 열쇠가 5화에서 다시 등장하는 대목입니다. 예비 열쇠를 받은 경위를 덧붙여 보세요.</span></div><label className="demo-field">5화 문제 문장 수정<textarea ref={textArea} rows={6} maxLength={1200} value={text} disabled={busy} onChange={e=>setText(e.target.value)} placeholder="예: 윤해주는 온전한 녹색 황동 열쇠로 사물함을 열었다."/></label><div className="demo-form-meta"><span>{text.length} / 1,200자</span><button disabled={busy} onClick={()=>setText(repairedSentence)}>수정안 다시 넣기</button></div><p className="muted">입력 문장과 관련 샘플 원문을 외부 AI에 전송합니다. 입력·결과 본문은 서버에 저장하지 않습니다.</p><p role="status">{availability}</p><div className="demo-form-meta"><span>{remaining===null?'하루 3회':`오늘 남은 검토 ${remaining}회`}</span><button className="primary" disabled={!ready||busy||!text.trim()||remaining===0} onClick={()=>void analyze()}>{busy?'수정 내용 분석 중…':'수정한 문장 분석하기'}</button></div>{error && <div role="alert" className="form-error"><p>{error}</p><p>이 요청의 분석 결과를 받지 못했습니다.</p><button onClick={onReview}>저장된 샘플 결과 살펴보기</button></div>}
      {result && <div className="demo-live-result" aria-live="polite"><span className="badge">방금 요청한 AI 분석 결과</span><span className="badge">{result.resolved?'수정안으로 해결 확인':({conflict:'충돌 후보',clear:'뚜렷한 충돌 없음',insufficient:'근거 부족'} as Record<string,string>)[result.verdict]||'검토 결과'}</span><p>{result.summary}</p><button className="primary" onClick={onGraph}>변경된 관계 지도 보기</button></div>}
    </section></div>;
}
