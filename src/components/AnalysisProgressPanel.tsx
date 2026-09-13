import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RotateCcw } from "lucide-react";
import type { AnalysisJob } from "../lib/types";

const STEP_LABELS: Record<string, string> = {
  idle: "대기",
  prepare: "분석 준비",
  parse: "원고 읽기",
  extract: "엔티티 추출",
  relations: "관계 정리",
  issues: "설정 점검",
  retrieve: "근거 검색",
  persist: "그래프 저장",
  validate: "결과 검증",
  completed: "분석 완료",
  failed: "분석 실패",
  cancelled: "분석 취소",
  gpt_index: "로컬 검색 준비",
  gpt_retrieve: "관련 원문 검색",
  gpt_request: "GPT 요청",
  gpt_models: "모델 확인",
  gpt_thread: "분석 연결 준비",
  gpt_start: "요청 전달",
  gpt_provider_retry: "GPT 서버에서 재시도 중",
  gpt_wait: "GPT 응답 대기",
  gpt_validate: "원문 근거 검증",
  gpt_validated: "구간 검증·저장",
  gpt_split: "큰 구간 나누기",
  gpt_repair: "응답 교정",
  gpt_partial: "성공 구간 체크포인트 보존 · 기존 결과 유지",
  gpt_queued: "대기",
  gpt_deferred: "미실행",
};

const ORDERED_STEPS = ["prepare", "parse", "extract", "relations", "issues", "retrieve", "persist", "validate"];
const WINDOW_LABELS: Record<string, string> = {completed: '검증 완료', failed: '실패', running: '처리 중', interrupted: '중단', deferred: '미실행', queued: '대기'};
const EFFORT_LABELS: Record<string, string> = {low: 'Low', medium: 'Medium', high: 'High', xhigh: 'XHigh'};

function clampProgress(progress: number) {
  return Math.max(0, Math.min(100, Math.round(progress)));
}

function formatRemainingSeconds(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "곧 완료";
  const rounded = Math.ceil(seconds);
  if (rounded < 60) return `약 ${rounded}초 남음`;
  const minutes = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return rest ? `약 ${minutes}분 ${String(rest).padStart(2, "0")}초 남음` : `약 ${minutes}분 남음`;
}

function titleForStatus(job: AnalysisJob) {
  if (job.status === "partial") return "일부 구간 재시도 필요";
  if (job.status === "failed") {
    return "분석 실패";
  }
  if (job.status === "cancelled") {
    return "분석 취소됨";
  }
  if (job.status === "completed") {
    return "분석 완료";
  }
  return "LLM 분석 진행 중";
}

function iconForStatus(job: AnalysisJob) {
  if (job.status === "partial") return <AlertTriangle aria-hidden="true" size={18} />;
  if (job.status === "failed") {
    return <AlertTriangle aria-hidden="true" size={18} />;
  }
  if (job.status === "cancelled") {
    return <AlertTriangle aria-hidden="true" size={18} />;
  }
  if (job.status === "completed") {
    return <CheckCircle2 aria-hidden="true" size={18} />;
  }
  return <Loader2 aria-hidden="true" className="analysis-progress-spinner" size={18} />;
}

export function AnalysisProgressPanel({ job, onRetry, onCancel }: { job: AnalysisJob; onRetry?: () => void; onCancel?: () => void }) {
  const [recordFilter, setRecordFilter] = useState(job.status === 'completed' ? 'completed' : 'attention');
  const [recordPage, setRecordPage] = useState(0);
  useEffect(() => { setRecordFilter(job.status === 'completed' ? 'completed' : 'attention'); setRecordPage(0); }, [job.id, job.status]);
  const progress = clampProgress(job.progress);
  const currentStepLabel = STEP_LABELS[job.current_step] ?? job.current_step;
  const hasSkippedWindows = job.status === "partial" || (job.status === "completed" && job.message.includes("실패하여 건너뛰었고"));
  const canRetry = Boolean(onRetry && (job.status === "failed" || job.status === "cancelled" || hasSkippedWindows));
  const stopped = ['failed', 'partial', 'cancelled'].includes(job.status);
  // Older releases kept running/queued records after their job had ended.
  const displayStatus = (status: string) => stopped && status === 'running' ? 'interrupted'
    : stopped && status === 'queued' ? 'deferred' : status;
  const windows = (job.window_details ?? []).map(window => ({...window, status: displayStatus(window.status)}));
  const completedCount = windows.filter(window => window.status === 'completed').length;
  const deferredCount = windows.filter((window) => window.status === "deferred").length;
  const measuredWindows = windows.filter((window) => window.status === "completed" && !window.reused && window.elapsed_seconds > 0);
  const remainingCount = windows.filter((window) => ["queued", "deferred", "running", "failed", "interrupted"].includes(window.status)).length;
  const estimatedRemaining = measuredWindows.length && remainingCount
    ? measuredWindows.reduce((total, window) => total + window.elapsed_seconds, 0) / measuredWindows.length * remainingCount
    : 0;
  const matches = (status: string, filter: string) => filter === 'all' || (filter === 'attention' ? ['failed','interrupted','running'].includes(status) : status === filter);
  const records = windows.filter(window => matches(window.status, recordFilter));
  const pageCount = Math.max(1, Math.ceil(records.length / 8));
  const currentPage = Math.min(recordPage, pageCount - 1);
  const visibleRecords = records.slice(currentPage * 8, currentPage * 8 + 8);

  return (
    <section className={`analysis-progress-panel is-${job.status}`} aria-live="polite">
      <div className="analysis-progress-header">
        <div className="analysis-progress-title">
          {iconForStatus(job)}
          <div>
            <strong>{titleForStatus(job)}</strong>
            <span>{currentStepLabel}</span>
          </div>
        </div>
        <output className="analysis-progress-percent">{stopped ? windows.length ? `${completedCount}/${windows.length}구간 검증` : '중단됨' : `${progress}%`}</output>
      </div>
      {!stopped && <div
        className="analysis-progress-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
        aria-label="LLM 분석 진행률"
      >
        <span style={{ width: `${progress}%` }} />
      </div>}
      <p>{job.message}</p>
      {job.status === "running" && onCancel && <button type="button" className="analysis-progress-cancel" onClick={onCancel}>분석 중단</button>}
      {!onRetry && ['failed', 'partial', 'cancelled'].includes(job.status) && <p>분석 화면에서 모델과 추론 강도를 선택해 다시 시작해 주세요.</p>}
      {windows.length > 0 && <p>검증 완료 {windows.filter((window) => window.status === "completed").length} / {windows.length}구간 · 재사용 {windows.filter((window) => window.reused).length}구간</p>}
      {windows.length > 0 && job.status === "running" && estimatedRemaining > 0 && <p className="analysis-progress-eta" aria-label="예상 잔여 시간">현재 처리 속도 기준 {formatRemainingSeconds(estimatedRemaining)} · 원고 크기와 GPT 응답에 따라 달라질 수 있습니다.</p>}
      {deferredCount > 0 && <p>아직 요청하지 않은 구간 {deferredCount}개가 있습니다. 오류 원인을 해결한 뒤 같은 원고·설정으로 재시도하면 저장된 성공 구간은 다시 요청하지 않습니다.</p>}
      {canRetry && onRetry && <div className="analysis-retry-summary">
        {job.review_context?.model && <><strong>재시도에 사용할 설정</strong><p>{job.review_context.model} · {job.review_context.effort ? EFFORT_LABELS[job.review_context.effort] ?? job.review_context.effort : '모델 기본값'}</p></>}
        <p>같은 원고·설정의 검증된 구간은 재사용합니다. 변경된 원고나 설정은 다시 검토하며, 새 요청에는 계정 사용량이 발생합니다.</p>
        <button type="button" className="analysis-progress-retry" onClick={onRetry}>
          <RotateCcw aria-hidden="true" size={15} /> {windows.length ? "남은 구간 이어서 분석" : "다시 분석"}
        </button>
      </div>}
      {windows.length > 0 && <details className="analysis-window-details" open>
        <summary>구간별 처리 기록 · {windows.length}개</summary>
        <div className="analysis-record-filters" role="group" aria-label="분석 기록 상태 필터">{[['attention','확인 필요'],['completed','검증 완료'],['deferred','미실행'],['all','전체']].map(([value,label])=><button type="button" key={value} aria-pressed={recordFilter===value} onClick={()=>{setRecordFilter(value);setRecordPage(0);}}>{label} {windows.filter(window=>matches(window.status,value)).length}</button>)}</div>
        {!records.length && <p className="list-empty">선택한 상태의 구간이 없습니다. 다른 상태를 선택해 주세요.</p>}
        <ul className="analysis-record-list">{visibleRecords.map((window) => <li key={window.index}>
          <strong>{window.document} · {window.index}번째 구간</strong>
          <span>{WINDOW_LABELS[window.status] ?? '대기'} · {STEP_LABELS[`gpt_${window.stage}`] ?? window.stage} · 시도 {window.attempts}회 · {Math.round(window.elapsed_seconds)}초{window.reused ? ' · 저장 결과 재사용' : ''}</span>
          {window.error && <p>{window.error}</p>}
          {window.error_code && <small className="analysis-record-error-code">오류 코드: {window.error_code}</small>}
          {!window.error && window.status === 'interrupted' && <p>실행이 종료되어 이 구간의 처리가 중단되었습니다.</p>}
          <small>원문 청크 {window.chunk_id}</small>
          {window.parts && window.parts.length > 1 && <details className="analysis-part-details"><summary>세부 구간 상태 보기</summary><ul aria-label="분할 구간 상태">{window.parts.filter((part) => part.status !== "split").map((part) => <li key={part.path}>
            <strong>세부 구간 {part.path.split("").map(side => side === "L" ? "앞부분" : "뒷부분").join(" · ")} · {WINDOW_LABELS[displayStatus(part.status)] ?? '대기'}</strong>
            <small>원문 청크 {part.chunk_ids.join(", ")}{part.reused ? " · 저장 결과 재사용" : ""}</small>
            {part.stage && <span>{STEP_LABELS[`gpt_${part.stage}`] ?? part.stage} · 시도 {part.attempts ?? 0}회 · {Math.round(part.elapsed_seconds ?? 0)}초</span>}
            {part.error && <p>{part.error}</p>}
          </li>)}</ul></details>}

        </li>)}</ul>
        {pageCount>1 && <nav className="list-pagination" aria-label="분석 기록 페이지"><button type="button" aria-label="분석 기록 이전 페이지" disabled={currentPage===0} onClick={()=>setRecordPage(currentPage-1)}>이전</button><span>{currentPage+1} / {pageCount}</span><button type="button" aria-label="분석 기록 다음 페이지" disabled={currentPage===pageCount-1} onClick={()=>setRecordPage(currentPage+1)}>다음</button></nav>}
      </details>}
      {!job.current_step.startsWith("gpt_") && windows.length === 0 && <div className="analysis-progress-steps" aria-label="분석 단계">
        {ORDERED_STEPS.map((step) => (
          <span
            key={step}
            className={
              step === job.current_step || progress >= stepProgressThreshold(step)
                ? "is-active"
                : undefined
            }
          >
            {STEP_LABELS[step]}
          </span>
        ))}
      </div>}
    </section>
  );
}

function stepProgressThreshold(step: string) {
  switch (step) {
    case "prepare":
      return 5;
    case "parse":
      return 18;
    case "extract":
      return 42;
    case "relations":
      return 70;
    case "issues":
      return 78;
    case "retrieve":
      return 86;
    case "persist":
      return 94;
    case "validate":
      return 96;
    default:
      return 100;
  }
}
