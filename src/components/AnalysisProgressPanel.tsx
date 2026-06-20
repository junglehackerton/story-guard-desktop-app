import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
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
};

const ORDERED_STEPS = ["prepare", "parse", "extract", "relations", "issues", "retrieve", "persist", "validate"];

function clampProgress(progress: number) {
  return Math.max(0, Math.min(100, Math.round(progress)));
}

function titleForStatus(job: AnalysisJob) {
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

export function AnalysisProgressPanel({ job }: { job: AnalysisJob }) {
  const progress = clampProgress(job.progress);
  const currentStepLabel = STEP_LABELS[job.current_step] ?? job.current_step;

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
        <output className="analysis-progress-percent">{progress}%</output>
      </div>
      <div
        className="analysis-progress-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
        aria-label="LLM 분석 진행률"
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      <p>{job.message}</p>
      <div className="analysis-progress-steps" aria-label="분석 단계">
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
      </div>
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
