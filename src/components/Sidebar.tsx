import { FilePlus2, Play, Plus, RefreshCw, Trash2 } from "lucide-react";
import type { AppSettings, LocalAiHealth, Project, StoryDocument } from "../lib/types";

interface SidebarProps {
  projects: Project[];
  selectedProject: Project | null;
  documents: StoryDocument[];
  localAi: LocalAiHealth | null;
  settings: AppSettings;
  loading: boolean;
  aiReady: boolean;
  onCreateProject: () => void;
  onSelectProject: (project: Project) => void;
  onImportDocument: () => void;
  onAnalyze: () => void;
  onRefresh: () => void;
  onGenerationModelChange: (model: string) => void;
  onDeleteDocument: (document: StoryDocument) => void;
}

export function Sidebar({
  projects,
  selectedProject,
  documents,
  localAi,
  settings,
  loading,
  aiReady,
  onCreateProject,
  onSelectProject,
  onImportDocument,
  onAnalyze,
  onRefresh,
  onGenerationModelChange,
  onDeleteDocument,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">SG</div>
        <div>
          <h1>Story Guard</h1>
          <p>로컬 설정 붕괴 감시</p>
        </div>
      </div>

      <div className={`runtime-status ${localAi?.ok ? "ok" : "warn"}`}>
        <strong>Local AI</strong>
        <span>{localAi?.message ?? "백엔드 시작 중"}</span>
      </div>

      <div className="settings-panel">
        <label htmlFor="generation-model">생성 모델</label>
        <select
          id="generation-model"
          value={settings.generation_model}
          onChange={(event) => onGenerationModelChange(event.target.value)}
        >
          {localAi?.models.map((model) => (
            <option key={model} value={model}>
              {model}
            </option>
          ))}
          {(localAi?.models.length ?? 0) === 0 && (
            <option value={settings.generation_model}>{settings.generation_model}</option>
          )}
          {settings.generation_model &&
            (localAi?.models.length ?? 0) > 0 &&
            !localAi?.models.includes(settings.generation_model) && (
              <option value={settings.generation_model}>{settings.generation_model}</option>
            )}
        </select>
        <span>
          임베딩: {settings.embedding_model}
          {!localAi?.ok ? " · 로컬 런타임 확인 필요" : ""}
        </span>
      </div>

      <div className="toolbar">
        <button onClick={onCreateProject} title="프로젝트 생성">
          <Plus size={16} />
          새 작품
        </button>
        <button onClick={onRefresh} title="새로고침">
          <RefreshCw size={16} />
        </button>
      </div>

      <section>
        <h2>작품</h2>
        <div className="project-list">
          {projects.map((project) => (
            <button
              key={project.id}
              className={selectedProject?.id === project.id ? "selected" : ""}
              onClick={() => onSelectProject(project)}
            >
              {project.title}
            </button>
          ))}
        </div>
      </section>

      <section>
        <div className="section-title-row">
          <h2>원고</h2>
          <span>{documents.length}</span>
        </div>
        <button className="wide-action" onClick={onImportDocument} disabled={!selectedProject}>
          <FilePlus2 size={16} />
          txt/md/docx 추가
        </button>
        <div className="document-list">
          {documents.map((document) => (
            <div key={document.id} className="document-row">
              <div className="document-main">
                <strong>{document.title}</strong>
                <span>{document.format}</span>
              </div>
              <button
                type="button"
                className="document-delete"
                title="원고 삭제"
                onClick={() => onDeleteDocument(document)}
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      </section>

      <button className="analyze-button" onClick={onAnalyze} disabled={!selectedProject || loading || !aiReady}>
        <Play size={16} />
        {loading ? "분석 중" : aiReady ? "분석 실행" : "LLM 설치 필요"}
      </button>
    </aside>
  );
}
