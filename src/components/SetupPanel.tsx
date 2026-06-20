import { CheckCircle2, Download, RefreshCw } from "lucide-react";
import type { EnvironmentSetupProgress, EnvironmentStatus } from "../lib/types";

interface SetupPanelProps {
  status: EnvironmentStatus | null;
  progress: EnvironmentSetupProgress | null;
  onStart: () => void;
  onRefresh: () => void;
}

export function SetupPanel({ status, progress, onStart, onRefresh }: SetupPanelProps) {
  const running = progress?.running ?? false;
  const ready = status?.ready ?? false;
  return (
    <section className={`setup-panel ${ready ? "ready" : ""}`}>
      <div className="setup-heading">
        <div>
          <span className="label">로컬 AI 환경</span>
          <h3>{ready ? "준비 완료" : (progress?.message ?? status?.message ?? "확인 중")}</h3>
        </div>
        <div className="setup-actions">
          <button onClick={onRefresh} title="환경 다시 확인" disabled={running}>
            <RefreshCw size={16} />
          </button>
          <button onClick={onStart} disabled={running || ready || status?.can_auto_install === false}>
            {ready ? <CheckCircle2 size={16} /> : <Download size={16} />}
            {running ? "준비 중" : ready ? "완료" : "모델 준비"}
          </button>
        </div>
      </div>

      <div className="setup-grid">
        <SetupItem label="Ollama 설치" ok={status?.ollama_installed} />
        <SetupItem label="Ollama 실행" ok={status?.ollama_running} />
        <SetupItem label={status?.embedding_model ?? "embeddinggemma"} ok={status?.embedding_model_ready} />
        <SetupItem label={status?.generation_model ?? "qwen2.5:3b"} ok={status?.generation_model_ready} />
      </div>

      {!ready && (
        <div className="setup-log">
          {(progress?.logs.length ? progress.logs : [status?.message ?? "환경 상태를 확인합니다."]).map(
            (line, index) => (
              <span key={`${line}-${index}`}>{line}</span>
            ),
          )}
          {progress?.error && <strong>{progress.error}</strong>}
        </div>
      )}
    </section>
  );
}

function SetupItem({ label, ok }: { label: string; ok: boolean | undefined }) {
  return (
    <div className={ok ? "setup-item ok" : "setup-item"}>
      <span>{ok ? "완료" : "필요"}</span>
      <strong>{label}</strong>
    </div>
  );
}
