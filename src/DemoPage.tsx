import { useState } from "react";
import { DEMO_DATA } from "./demoData";
import "./demo.css";

type Tab = "overview" | "graph" | "review" | "foreshadow";

export default function DemoPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [sentence, setSentence] = useState("");
  const [analysis, setAnalysis] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [used, setUsed] = useState(() => window.localStorage.getItem("story-guard-demo-used") === "1");

  async function runAnalysis() {
    if (!sentence.trim() || used || busy) return;
    setBusy(true);
    try {
      const apiBase = (import.meta.env.VITE_DEMO_API_URL || "").replace(/\/$/, "");
      const response = await fetch(`${apiBase}/api/demo/analyze`, { method: "POST", headers: { "content-type": "application/json" }, credentials: "include", body: JSON.stringify({ text: sentence.trim() }) });
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "분석을 완료하지 못했습니다.");
      const result = await response.json() as { summary?: string };
      setAnalysis(result.summary || "분석 결과가 준비되었습니다.");
      window.localStorage.setItem("story-guard-demo-used", "1");
      setUsed(true);
    } catch (error) {
      setAnalysis(error instanceof Error ? error.message : "분석을 완료하지 못했습니다.");
    } finally { setBusy(false); }
  }

  return <div className="demo-shell">
    <header className="demo-nav"><a className="demo-brand" href="/demo"><span>SG</span> STORY GUARD</a><span className="demo-nav-note">작가의 연결을 지키는 작업실</span><a className="demo-desktop-link" href="/">데스크톱 작업실 열기</a></header>
    <main>
      <section className="demo-hero"><div className="demo-hero-copy"><span className="demo-kicker">PUBLIC DEMO · PRE-INDEXED NOVEL</span><h1>원고를 읽는 동안<br /><em>설정의 연결</em>을 지켜드립니다.</h1><p>{DEMO_DATA.subtitle} 임베딩은 미리 준비되어 있어 지금 바로 결과를 탐색할 수 있습니다.</p><div className="demo-hero-actions"><button className="demo-primary" onClick={() => document.getElementById("demo-workbench")?.scrollIntoView({ behavior: "smooth" })}>데모 시작하기 <span>↓</span></button><span className="demo-limit">GPT 분석 1회 제공</span></div></div><div className="demo-hero-card"><span className="demo-card-label">현재 데모 작품</span><strong>{DEMO_DATA.title}</strong><div className="demo-card-stats"><span><b>10</b>화</span><span><b>138</b>대상</span><span><b>205</b>관계</span></div><div className="demo-mini-graph">{DEMO_DATA.entities.map((entity, index) => <i key={entity.name} className={entity.tone} style={{ left: `${15 + (index * 19) % 75}%`, top: `${22 + (index * 31) % 58}%` }}>{entity.name.slice(0, 1)}</i>)}</div></div></section>
      <section className="demo-workbench" id="demo-workbench"><div className="demo-workbench-head"><div><span className="demo-kicker">EXPLORE THE WORK</span><h2>{DEMO_DATA.title}</h2></div><span className="demo-index-badge">임베딩 준비 완료</span></div><nav className="demo-tabs" aria-label="데모 기능"><button className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>원고</button><button className={tab === "graph" ? "active" : ""} onClick={() => setTab("graph")}>관계 지도 <b>{DEMO_DATA.relations.length}</b></button><button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")}>검토 결과 <b>{DEMO_DATA.reviews.length}</b></button><button className={tab === "foreshadow" ? "active" : ""} onClick={() => setTab("foreshadow")}>떡밥 후보 <b>{DEMO_DATA.foreshadowing.length}</b></button></nav>
        {tab === "overview" && <div className="demo-overview"><article className="demo-paper"><span className="demo-paper-meta">1화 · 문을 여는 사람</span><p>{DEMO_DATA.excerpt}</p><div className="demo-paper-rule"><span>작가의 원문</span><b>원문은 로컬에 보관됩니다</b></div></article><aside className="demo-side-note"><span className="demo-kicker">HOW IT WORKS</span><h3>원문을 먼저 읽고,<br />연결을 나중에 확인합니다.</h3><p>미리 계산한 검색 색인에서 관련 근거를 찾고, AI가 제안한 후보를 작가가 직접 판단합니다.</p><div className="demo-flow"><span>01 <b>원문</b></span><span>02 <b>연결</b></span><span>03 <b>판단</b></span></div></aside></div>}
        {tab === "graph" && <div className="demo-panel"><div className="demo-graph-canvas"><div className="demo-graph-lines">{DEMO_DATA.relations.map((relation, index) => <span key={relation.label} className={relation.state === "확인 필요" ? "warn" : ""} style={{ transform: `rotate(${index * 38 - 25}deg)` }} />)}</div><div className="demo-graph-center">윤해주</div>{DEMO_DATA.entities.slice(1).map((entity, index) => <div key={entity.name} className={`demo-node ${entity.tone}`} style={{ left: `${14 + index * 21}%`, top: `${18 + (index % 2) * 54}%` }}>{entity.name}</div>)}</div><div className="demo-inspector"><span className="demo-kicker">SELECTED ENTITY</span><h3>윤해주</h3><p>백로호텔 지하 금고의 계약과 사라진 기록을 추적하는 인물입니다.</p><strong>직접 연결 3개</strong><button onClick={() => setTab("review")}>관련 검토 결과 보기 →</button></div></div>}
        {tab === "review" && <div className="demo-list">{DEMO_DATA.reviews.map(review => <article className="demo-review-card" key={review.title}><span className="demo-status">{review.status}</span><h3>{review.title}</h3><p>{review.body}</p><div><button onClick={() => setTab("graph")}>관계 지도에서 보기 →</button><button>원문 근거 열기</button></div></article>)}</div>}
        {tab === "foreshadow" && <div className="demo-list">{DEMO_DATA.foreshadowing.map(item => <article className="demo-foreshadow-card" key={item.title}><div><span className="demo-status">{item.status}</span><span className="demo-chapter">등장 {item.chapter}</span></div><h3>{item.title}</h3><p>이후 답을 기대하게 만드는 구체적인 질문입니다. 작가가 회수 여부를 결정합니다.</p><button onClick={() => setTab("graph")}>관계 지도에서 확인 →</button></article>)}</div>}
      </section>
      <section className="demo-ai"><div><span className="demo-kicker">ONE-TIME GPT REVIEW</span><h2>내 문장 하나를<br /><em>직접 분석해 보세요.</em></h2><p>데모 방문자당 한 번만 사용할 수 있습니다. 분석 결과는 이 브라우저에만 저장됩니다.</p></div><div className="demo-ai-form"><textarea value={sentence} onChange={event => setSentence(event.target.value)} placeholder="예: 윤해주는 금고 열쇠를 민규백에게 건넸다." disabled={used} /><div><span>{used ? "이 브라우저의 데모 분석을 사용했습니다." : "남은 분석 1회"}</span><button className="demo-primary" disabled={used || busy || !sentence.trim()} onClick={() => void runAnalysis()}>{busy ? "분석 중…" : used ? "분석 완료" : "GPT로 1회 분석"}</button></div>{analysis && <p className="demo-analysis-result" role="status">{analysis}</p>}</div></section>
    </main><footer className="demo-footer"><span>STORY GUARD</span><span>미리 색인된 원고로 기능을 먼저 경험해 보세요.</span></footer>
  </div>;
}
