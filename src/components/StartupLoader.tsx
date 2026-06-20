import { LoaderCircle, RefreshCw } from "lucide-react";

export type StartupMode = "loading" | "error";

export interface StartupStatus {
  visible: boolean;
  mode: StartupMode;
  message: string;
  detail: string;
  progress: number;
}

interface StartupLoaderProps {
  status: StartupStatus;
  onRetry: () => void;
}

export function StartupLoader({ status, onRetry }: StartupLoaderProps) {
  if (!status.visible) {
    return null;
  }

  const progress = Math.min(100, Math.max(0, Math.round(status.progress)));
  const failed = status.mode === "error";

  return (
    <div className={`startup-loader ${failed ? "error" : ""}`} role="status" aria-live="polite">
      <div className="startup-loader-inner">
        <div className="startup-brand">
          <div className="brand-mark">SG</div>
          <div>
            <h1>Story Guard</h1>
            <p>로컬 작업실을 준비합니다.</p>
          </div>
        </div>
        <div className="startup-copy">
          <span className="label">{failed ? "시작 실패" : "시스템 로딩"}</span>
          <h2>{status.message}</h2>
          <p>{status.detail}</p>
        </div>
        {!failed && (
          <div className="startup-progress" aria-label="초기 로딩 진행률">
            <div className="startup-progress-meta">
              <span>준비 중</span>
              <strong>{progress}%</strong>
            </div>
            <div
              className="startup-progress-track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress}
            >
              <div style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}
        {failed ? (
          <button type="button" className="startup-retry" onClick={onRetry}>
            <RefreshCw size={16} />
            다시 확인
          </button>
        ) : (
          <LoaderCircle className="startup-spinner" size={28} aria-hidden="true" />
        )}
      </div>
    </div>
  );
}
