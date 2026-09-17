import { useState } from "react";
import { CheckCircle2, Download, RefreshCw } from "lucide-react";
import type { EnvironmentSetupProgress, EnvironmentStatus } from "../lib/types";

interface SetupPanelProps {
  status: EnvironmentStatus | null;
  progress: EnvironmentSetupProgress | null;
  onStart: (model: string) => void;
  onRefresh: () => void;
}

export function SetupPanel({ status, progress, onStart, onRefresh }: SetupPanelProps) {
  const [selection, setSelection] = useState<string | null>(null);
  const model = selection ?? status?.embedding_model ?? "Qwen3-Embedding-0.6B-Q8_0.gguf";
  const changed = model !== status?.embedding_model;
  const running = progress?.running ?? false;
  const ready = (status?.embedding_model_ready ?? false) && !changed;
  return (
    <section className={`setup-panel ${ready ? "ready" : ""}`}>
      <div className="setup-heading">
        <div>
          <span className="label">원고 검색 모델</span>
          <h3>{ready ? "준비 완료" : (progress?.message ?? status?.message ?? "확인 중")}</h3>
        </div>
        <div className="setup-actions">
          <button onClick={onRefresh} title="환경 다시 확인" disabled={running}>
            <RefreshCw size={16} />
          </button>
          <button onClick={() => onStart(model)} disabled={running || ready || status?.can_auto_install === false}>
            {ready ? <CheckCircle2 size={16} /> : <Download size={16} />}
            {running ? "준비 중" : ready ? "완료" : "선택 모델 준비·적용"}
          </button>
        </div>
      </div>

      <label>원고 임베딩 모델
        <select aria-label="원고 임베딩 모델" value={model} disabled={running} onChange={(event) => setSelection(event.target.value)}>
          <option value="Qwen3-Embedding-0.6B-Q8_0.gguf">Qwen · 근거 검색 우선 · 파일 약 639MB</option>
          <option value="embeddinggemma-300m">EmbeddingGemma · 처리 속도 우선 · 파일 약 1.27GB</option>
        </select>
      </label>
      <div className="setup-model-evidence" aria-live="polite">
        <strong>현재 검증 상태</strong>
        <span>
          {model === "embeddinggemma-300m"
            ? "검증 샘플 기준 Gemma · 152 청크 31.95초 · Top-4 29/40"
            : "실측 62,000자·150청크 · 106.9초 · 1.40청크/초 · 최대 RSS 약 2.27GB (Mac 기준)"}
        </span>
      </div>
      <p>모델 변경 후 작품을 분석하면 해당 모델의 검색 인덱스를 준비합니다. 원고는 유지되며, 처음 전환할 때 시간이 걸릴 수 있습니다.</p>
      {model === "embeddinggemma-300m" && <>
        <p>Gemma는 Hugging Face 이용 조건 동의와 로컬 계정 연결이 필요합니다. 기기 가속과 배치 처리를 사용하며 속도는 기기마다 다릅니다.</p>
        <p className="setup-memory-note">장편 색인 실측에서 임베딩 워커 최대 메모리는 약 1.66GB였습니다. 메모리가 제한된 기기에서는 Qwen을 선택하거나 회차 범위를 나누어 준비하세요.</p>
      </>}
      {model !== "embeddinggemma-300m" && <p className="setup-memory-note">Qwen 실측(62,000자·150청크)에서 최대 RSS 약 2.27GB, 1.40청크/초였습니다. 검색 품질을 우선할 때 선택하고, 메모리가 제한된 기기는 Gemma 또는 회차 범위 분할을 고려하세요.</p>}
      <div className="setup-grid">
        <SetupItem label="로컬 AI 런타임" ok={status?.runtime_installed} />
        <SetupItem label="모델 폴더 설정" ok={Boolean(status?.model_dir)} />
        <SetupItem label={`임베딩 · ${status?.embedding_model ?? "Qwen3-Embedding-0.6B-Q8_0.gguf"}`} ok={status?.embedding_model_ready} />
        <SetupItem label={`로컬 분석 · ${status?.generation_model ?? "qwen2.5-1.5b-instruct-q4_k_m.gguf"}`} ok={status?.generation_model_ready} />
      </div>

      {ready && <p className="setup-note">모델 파일 준비 완료 · 첫 분석에서 실제 실행 환경을 확인합니다.</p>}

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
