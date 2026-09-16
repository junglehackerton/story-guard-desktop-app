import { useEffect, useRef, useState } from 'react';
import { sample } from './data';
export type LiveAnalysis = {text: string; summary: string; verdict: string; evidence: {id:number;document_id:number;text:string}[]; remaining: number; resolved?: boolean};
const base = (import.meta.env.VITE_DEMO_API_URL || '').replace(/\/$/, '');
const staticDemo = import.meta.env.VITE_DEMO_STATIC === 'true';
export function DemoAnalysis({active=true,onSource,onGraph,onReview,onResult}: {active?:boolean;onSource:(id:number,quote?:string)=>void;onGraph:()=>void;onReview:()=>void;onResult:(result:LiveAnalysis|null)=>void}) {
  const [text,setText] = useState('');
  const [chapter,setChapter] = useState(9);
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
      setText('');
      setResult(null);
      setOverrideDraft({});
      setOverrides({});
      setError('');
      lastVerdict.current=null;
      return;
    }
    if(statusLoaded.current) return;
    const controller = new AbortController();
    fetch(`${base}/api/demo/status`, {credentials:'include',signal:controller.signal}).then(async r=>{
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
      const response=await fetch(`${base}/api/demo/analyze`,{method:'POST',credentials:'include',signal:controller.signal,headers:{'content-type':'application/json'},body:JSON.stringify({text:text.trim(),end_chapter:chapter,version:sample.version,request_id:request.current.id,overrides:Object.entries(nextOverrides).map(([id,value])=>({id:Number(id),text:value}))})});
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
  return <div className="demo-analysis-grid"><section className="surface"><h2>분석 대상</h2><div className="soft-card"><h3>{sample.project.title}</h3><p>전체 원고 · {sample.documents.length}편</p><p>철거 직전 호텔에 돌아온 윤해주. 인물의 기억과 물건의 행적을 따라 설정의 빈틈을 살펴보세요.</p></div><h3>준비된 분석 결과</h3><p className="muted">{sample.provenance}</p><div className="demo-result-links"><button onClick={onReview}>검토 결과 · {sample.graph.issues.length}개</button><button onClick={onGraph}>관계 지도 · {sample.graph.relations.length}개</button><button onClick={()=>onSource(sample.documents[0].id)}>원고 읽기 · 10화</button></div></section>
    <section className="surface"><span className="badge">실시간 AI 분석 · 입력 후 요청</span><h2>새 문장 검토</h2><p>이 작품에 추가할 문장이 기존 설정과 맞는지 확인하세요. 샘플 원고는 변경되지 않습니다.</p><label className="demo-field">기준 원고 범위<select value={chapter} onChange={e=>setChapter(Number(e.target.value))} disabled={busy}>{sample.documents.map(d=><option key={d.id} value={d.chapter_index}>1화부터 {d.chapter_index+1}화까지</option>)}</select></label><label className="demo-field">추가할 문장<textarea ref={textArea} rows={6} maxLength={1200} value={text} disabled={busy} onChange={e=>setText(e.target.value)} placeholder="예: 서우는 올해 스물다섯 살이라고 말했다."/></label><div className="demo-form-meta"><span>{text.length} / 1,200자</span><button disabled={busy} onClick={()=>{setText('윤해주는 온전한 녹색 황동 열쇠를 주머니에서 꺼내 사물함을 열었다.');setChapter(2);}}>예문 넣기</button></div><p className="muted">입력 문장과 관련 샘플 원문을 외부 AI에 전송합니다. 입력·결과 본문은 서버에 저장하지 않습니다.</p><p role="status">{availability}</p><div className="demo-form-meta"><span>{remaining===null?'하루 3회':`오늘 남은 검토 ${remaining}회`}</span><button className="primary" disabled={!ready||busy||!text.trim()||remaining===0} onClick={()=>void analyze()}>{busy?'근거 검색·검토 중…':'GPT로 검토하기'}</button></div>{error && <div role="alert" className="form-error"><p>{error}</p><p>이 요청의 분석 결과를 받지 못했습니다.</p><button onClick={onReview}>저장된 샘플 결과 살펴보기</button></div>}
      {result && <div className="demo-live-result" aria-live="polite"><span className="badge">방금 요청한 AI 분석 결과</span><span className="badge">{result.resolved?'수정안으로 해결 확인':({conflict:'충돌 후보',clear:'뚜렷한 충돌 없음',insufficient:'근거 부족'} as Record<string,string>)[result.verdict]||'검토 결과'}</span><p>{result.summary}</p><p className="muted">기존 근거를 직접 수정해 같은 문장을 다시 검토할 수 있습니다. 수정안은 현재 방문자에게만 임시 적용되고 샘플 원문에는 저장되지 않습니다.</p><button className="text-action" onClick={()=>textArea.current?.focus()}>문장 수정하기</button><button className="text-action" onClick={()=>{setOverrides({});setOverrideDraft(Object.fromEntries(result.evidence.map(e=>[e.id,e.text])));}}>근거 수정 초기화</button><h3>원문 근거 수정 시뮬레이션</h3><p className="muted">충돌을 만든 기존 설정을 어떻게 고쳤는지 적고, 아래 버튼으로 다시 분석하세요.</p>{result.evidence.map((e:{id:number;document_id:number;text:string})=><blockquote key={e.id}><label className="demo-field">{e.document_id}화 근거<textarea rows={4} value={overrideDraft[e.id] ?? e.text} onChange={event=>setOverrideDraft(current=>({...current,[e.id]:event.target.value}))} disabled={busy}/></label><div className="demo-form-meta"><button onClick={()=>{const next={...overrides,[e.id]:overrideDraft[e.id] ?? e.text};setOverrides(next);void analyze(next);}} disabled={busy||!text.trim()}>수정한 근거로 다시 검토</button><button onClick={()=>onSource(e.document_id,e.text)}>이 회차 원고 열기</button></div></blockquote>)}</div>}
    </section></div>;
}
