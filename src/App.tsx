import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { Check, Pencil, X } from "lucide-react";
import { api } from "./lib/api";
import { ensureDesktopBackend, isTauriRuntime } from "./lib/desktopBackend";
import { ENTITY_TYPE_LABELS } from "./lib/labels";
import type {
  EntityNode,
  EntityType,
  EnvironmentSetupProgress,
  EnvironmentStatus,
  EvidenceChunk,
  GraphPayload,
  IssueStatus,
  AppSettings,
  OllamaHealth,
  Project,
  StoryDocument,
} from "./lib/types";
import { GraphView } from "./components/GraphView";
import { Inspector } from "./components/Inspector";
import { Sidebar } from "./components/Sidebar";
import { SetupPanel } from "./components/SetupPanel";

const EMPTY_GRAPH: GraphPayload = {
  entities: [],
  relations: [],
  issues: [],
};

const DEFAULT_SETTINGS: AppSettings = {
  generation_model: "",
  embedding_model: "embeddinggemma",
};

const ENTITY_TYPES: EntityType[] = [
  "character",
  "place",
  "organization",
  "item",
  "event",
  "rule",
  "foreshadowing",
];

type RelationScope = "core" | "all";
const SELECTED_PROJECT_STORAGE_KEY = "storyGuard.selectedProjectId";

function strongestRelationPerPair(relations: GraphPayload["relations"]) {
  const bestByPair = new Map<string, GraphPayload["relations"][number]>();
  for (const relation of [...relations].sort(
    (left, right) =>
      (right.strength ?? right.confidence ?? 0) - (left.strength ?? left.confidence ?? 0),
  )) {
    const pairKey = [relation.source_entity_id, relation.target_entity_id].sort((a, b) => a - b).join("-");
    if (!bestByPair.has(pairKey)) {
      bestByPair.set(pairKey, relation);
    }
  }
  return [...bestByPair.values()].sort(
    (left, right) =>
      (right.strength ?? right.confidence ?? 0) - (left.strength ?? left.confidence ?? 0),
  );
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [projectTitleDraft, setProjectTitleDraft] = useState("");
  const [editingProjectTitle, setEditingProjectTitle] = useState(false);
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [newProjectTitle, setNewProjectTitle] = useState("");
  const [documentPathModalOpen, setDocumentPathModalOpen] = useState(false);
  const [documentPathDraft, setDocumentPathDraft] = useState("");
  const [documents, setDocuments] = useState<StoryDocument[]>([]);
  const [graph, setGraph] = useState<GraphPayload>(EMPTY_GRAPH);
  const [selectedEntity, setSelectedEntity] = useState<EntityNode | null>(null);
  const [relationScope, setRelationScope] = useState<RelationScope>("core");
  const [visibleTypes, setVisibleTypes] = useState<Set<EntityType>>(
    () => new Set(ENTITY_TYPES),
  );
  const [evidenceByIssueId, setEvidenceByIssueId] = useState<Record<number, EvidenceChunk[]>>({});
  const [ollama, setOllama] = useState<OllamaHealth | null>(null);
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [setupStatus, setSetupStatus] = useState<EnvironmentStatus | null>(null);
  const [setupProgress, setSetupProgress] = useState<EnvironmentSetupProgress | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("백엔드 연결을 확인하는 중입니다.");
  const dataRequestIdRef = useRef(0);

  const openIssues = useMemo(
    () => graph.issues.filter((issue) => issue.status !== "ignored"),
    [graph.issues],
  );

  const filteredGraph = useMemo(() => {
    const entities = graph.entities.filter((entity) => visibleTypes.has(entity.type));
    const visibleIds = new Set(entities.map((entity) => entity.id));
    const relations = graph.relations
      .filter(
        (relation) =>
          visibleIds.has(relation.source_entity_id) && visibleIds.has(relation.target_entity_id),
      )
      .filter((relation) => {
        if (relationScope === "all") {
          return true;
        }
        return !relation.is_weak && relation.type !== "co_occurs" && relation.confidence >= 0.68;
      });
    const scopedRelations =
      relationScope === "core" ? strongestRelationPerPair(relations).slice(0, 46) : relations;
    let scopedEntities = entities;
    if (relationScope === "core" && scopedRelations.length > 0) {
      const connectedIds = new Set<number>();
      for (const relation of scopedRelations) {
        connectedIds.add(relation.source_entity_id);
        connectedIds.add(relation.target_entity_id);
      }
      scopedEntities = entities.filter((entity) => connectedIds.has(entity.id));
    }
    return {
      ...graph,
      entities: scopedEntities,
      relations: scopedRelations,
    };
  }, [graph, relationScope, visibleTypes]);

  const refreshOllama = useCallback(async () => {
    try {
      setOllama(await api.ollamaHealth());
    } catch (error) {
      setOllama({
        ok: false,
        base_url: "http://localhost:11434/api",
        message: error instanceof Error ? error.message : "Ollama 상태 확인 실패",
        models: [],
      });
    }
  }, []);

  const refreshProjectData = useCallback(async (project: Project | null) => {
    const requestId = dataRequestIdRef.current + 1;
    dataRequestIdRef.current = requestId;
    if (!project) {
      setDocuments([]);
      setGraph(EMPTY_GRAPH);
      return;
    }
    const nextDocuments = await api.listDocuments(project.id);
    if (dataRequestIdRef.current !== requestId) {
      return;
    }
    setDocuments(nextDocuments);
    const nextGraph = await api.graph(project.id);
    if (dataRequestIdRef.current !== requestId) {
      return;
    }
    setGraph(nextGraph);
  }, []);

  const refreshProjects = useCallback(async (preferredProjectId?: number | null) => {
    const nextProjects = await api.listProjects();
    const storedProjectId = Number(window.localStorage.getItem(SELECTED_PROJECT_STORAGE_KEY) ?? 0);
    const targetProjectId = preferredProjectId ?? selectedProject?.id ?? storedProjectId;
    const nextSelected =
      nextProjects.find((project) => project.id === targetProjectId) ?? nextProjects[0] ?? null;
    setProjects(nextProjects);
    setSelectedProject(nextSelected);
    if (nextSelected) {
      window.localStorage.setItem(SELECTED_PROJECT_STORAGE_KEY, String(nextSelected.id));
    }
    return nextSelected;
  }, [selectedProject?.id]);

  const refreshSettings = useCallback(async () => {
    setSettings(await api.settings());
  }, []);

  const refreshSetup = useCallback(async () => {
    const [status, progress] = await Promise.all([api.setupStatus(), api.setupProgress()]);
    setSetupStatus(status);
    setSetupProgress(progress);
    return status;
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      const backendMessage = await ensureDesktopBackend();
      setNotice(backendMessage);
      const nextSelectedProject = await refreshProjects();
      await Promise.all([
        refreshProjectData(nextSelectedProject),
        refreshOllama(),
        refreshSettings(),
        refreshSetup(),
      ]);
      setNotice("준비 완료");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "백엔드 연결 실패");
    }
  }, [refreshOllama, refreshProjectData, refreshProjects, refreshSettings, refreshSetup]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    setProjectTitleDraft(selectedProject?.title ?? "");
    setEditingProjectTitle(false);
  }, [selectedProject?.id, selectedProject?.title]);

  useEffect(() => {
    if (!setupProgress?.running) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void api.setupProgress().then(async (progress) => {
        setSetupProgress(progress);
        if (!progress.running) {
          await Promise.all([refreshSetup(), refreshOllama(), refreshSettings()]);
        }
      });
    }, 2000);
    return () => window.clearInterval(intervalId);
  }, [refreshOllama, refreshSettings, refreshSetup, setupProgress?.running]);

  useEffect(() => {
    const issueIds = graph.issues.map((issue) => issue.id);
    if (issueIds.length === 0) {
      setEvidenceByIssueId({});
      return;
    }
    let cancelled = false;
    void Promise.all(
      issueIds.map(async (issueId) => {
        try {
          return [issueId, await api.issueEvidence(issueId)] as const;
        } catch {
          return [issueId, []] as const;
        }
      }),
    ).then((entries) => {
      if (!cancelled) {
        setEvidenceByIssueId(Object.fromEntries(entries));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [graph.issues]);

  function toggleEntityType(type: EntityType) {
    setVisibleTypes((current) => {
      const next = new Set(current);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }

  function selectProject(project: Project) {
    window.localStorage.setItem(SELECTED_PROJECT_STORAGE_KEY, String(project.id));
    setSelectedProject(project);
    setSelectedEntity(null);
    setDocuments([]);
    setGraph(EMPTY_GRAPH);
    void refreshProjectData(project);
  }

  function createProject() {
    setNewProjectTitle("");
    setProjectModalOpen(true);
  }

  async function submitNewProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = newProjectTitle.trim();
    if (!title) {
      setNotice("작품 제목을 입력해 주세요.");
      return;
    }
    try {
      const project = await api.createProject(title);
      setProjects((current) => [project, ...current]);
      setSelectedProject(project);
      window.localStorage.setItem(SELECTED_PROJECT_STORAGE_KEY, String(project.id));
      setDocuments([]);
      setGraph(EMPTY_GRAPH);
      setSelectedEntity(null);
      setProjectModalOpen(false);
      setNewProjectTitle("");
      setNotice(`작품 생성: ${project.title}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "작품 생성 실패");
    }
  }

  async function saveProjectTitle(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!selectedProject) {
      return;
    }
    const title = projectTitleDraft.trim();
    if (!title) {
      setNotice("작품 제목을 입력해 주세요.");
      return;
    }
    if (title === selectedProject.title) {
      setEditingProjectTitle(false);
      return;
    }
    try {
      const updated = await api.updateProjectTitle(selectedProject.id, title);
      setSelectedProject(updated);
      setProjects((current) =>
        current.map((project) => (project.id === updated.id ? updated : project)),
      );
      setEditingProjectTitle(false);
      setNotice(`작품 제목 저장: ${updated.title}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "작품 제목 저장 실패");
    }
  }

  async function importDocumentPath(path: string) {
    if (!selectedProject) {
      return false;
    }
    const filePath = path.trim();
    if (!filePath) {
      setNotice("원고 파일 경로를 입력해 주세요.");
      return false;
    }
    setLoading(true);
    try {
      const document = await api.importDocument(selectedProject.id, filePath);
      setDocuments((current) =>
        current.some((item) => item.id === document.id) ? current : [...current, document],
      );
      setGraph(EMPTY_GRAPH);
      setSelectedEntity(null);
      setNotice(`원고 추가: ${document.title} · 분석을 다시 실행하세요.`);
      void refreshProjectData(selectedProject);
      return true;
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "원고 추가 실패");
      return false;
    } finally {
      setLoading(false);
    }
  }

  async function importDocument() {
    if (!selectedProject) {
      return;
    }
    if (isTauriRuntime()) {
      const selected = await open({
        multiple: false,
        filters: [{ name: "Manuscript", extensions: ["txt", "md", "docx"] }],
      });
      if (typeof selected === "string") {
        await importDocumentPath(selected);
      }
      return;
    }
    setDocumentPathDraft("");
    setDocumentPathModalOpen(true);
  }

  async function submitDocumentPath(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const imported = await importDocumentPath(documentPathDraft);
    if (imported) {
      setDocumentPathModalOpen(false);
      setDocumentPathDraft("");
    }
  }

  async function deleteDocument(document: StoryDocument) {
    if (!selectedProject) {
      return;
    }
    const confirmed = window.confirm(`'${document.title}' 원고를 삭제할까요? 분석 그래프도 다시 비워집니다.`);
    if (!confirmed) {
      return;
    }
    setLoading(true);
    try {
      await api.deleteDocument(document.id);
      setDocuments((current) => current.filter((item) => item.id !== document.id));
      setGraph(EMPTY_GRAPH);
      setSelectedEntity(null);
      await refreshProjectData(selectedProject);
      setNotice(`원고 삭제: ${document.title}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "원고 삭제 실패");
    } finally {
      setLoading(false);
    }
  }

  async function analyze() {
    if (!selectedProject) {
      return;
    }
    setLoading(true);
    setNotice("분석 중입니다.");
    try {
      const result = await api.analyzeProject(selectedProject.id);
      await refreshProjectData(selectedProject);
      setNotice(
        `분석 완료: 엔티티 ${result.entity_count}개, 관계 ${result.relation_count}개, 이슈 ${result.issue_count}개`,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "분석 실패");
    } finally {
      setLoading(false);
    }
  }

  async function updateIssueStatus(issueId: number, status: IssueStatus) {
    try {
      const updated = await api.updateIssueStatus(issueId, status);
      setGraph((current) => ({
        ...current,
        issues: current.issues.map((issue) => (issue.id === issueId ? updated : issue)),
      }));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "이슈 상태 변경 실패");
    }
  }

  async function updateGenerationModel(model: string) {
    try {
      const updated = await api.updateSettings({
        ...settings,
        generation_model: model,
      });
      setSettings(updated);
      setNotice(model ? `생성 모델 저장: ${model}` : "생성 모델을 휴리스틱 fallback으로 설정했습니다.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "설정 저장 실패");
    }
  }

  async function startEnvironmentSetup() {
    try {
      setNotice("로컬 AI 모델을 준비합니다.");
      const progress = await api.runSetup({
        install_ollama: false,
        pull_embedding_model: true,
        pull_generation_model: true,
        embedding_model: setupStatus?.embedding_model ?? settings.embedding_model,
        generation_model:
          settings.generation_model || setupStatus?.generation_model || "qwen2.5:3b",
      });
      setSetupProgress(progress);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "환경 설정 시작 실패");
    }
  }

  async function refreshEnvironmentSetup() {
    try {
      await Promise.all([refreshSetup(), refreshOllama(), refreshSettings()]);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "환경 상태 확인 실패");
    }
  }

  return (
    <div className="app-shell">
      <Sidebar
        projects={projects}
        selectedProject={selectedProject}
        documents={documents}
        ollama={ollama}
        settings={settings}
        loading={loading}
        onCreateProject={createProject}
        onSelectProject={selectProject}
        onImportDocument={importDocument}
        onAnalyze={analyze}
        onRefresh={refreshAll}
        onGenerationModelChange={updateGenerationModel}
        onDeleteDocument={deleteDocument}
      />
      <main className="workspace">
        <header className="workspace-header">
          <div className="title-area">
            <span className="label">작품 작업실</span>
            {editingProjectTitle && selectedProject ? (
              <form className="project-title-editor" onSubmit={saveProjectTitle}>
                <input
                  autoFocus
                  value={projectTitleDraft}
                  maxLength={120}
                  onChange={(event) => setProjectTitleDraft(event.target.value)}
                  aria-label="작품 제목"
                />
                <button type="submit" title="작품 제목 저장">
                  <Check size={16} />
                </button>
                <button
                  type="button"
                  title="취소"
                  onClick={() => {
                    setProjectTitleDraft(selectedProject.title);
                    setEditingProjectTitle(false);
                  }}
                >
                  <X size={16} />
                </button>
              </form>
            ) : (
              <div className="project-title-row">
                <h2>{selectedProject?.title ?? "작품 없음"}</h2>
                {selectedProject && (
                  <button
                    className="icon-button"
                    type="button"
                    title="작품 제목 편집"
                    onClick={() => setEditingProjectTitle(true)}
                  >
                    <Pencil size={16} />
                  </button>
                )}
              </div>
            )}
          </div>
          <div className="status-strip">
            <span>{notice}</span>
            <strong>{filteredGraph.entities.length} nodes</strong>
            <strong>{filteredGraph.relations.length}/{graph.relations.length} links</strong>
          </div>
        </header>
        {(!setupStatus?.ready || setupProgress?.running) && (
          <SetupPanel
            status={setupStatus}
            progress={setupProgress}
            onStart={startEnvironmentSetup}
            onRefresh={refreshEnvironmentSetup}
          />
        )}
        <div className="graph-controls">
          <div className="relation-scope" aria-label="관계 표시 범위">
            <button
              type="button"
              className={relationScope === "core" ? "active" : ""}
              onClick={() => setRelationScope("core")}
            >
              핵심 관계
            </button>
            <button
              type="button"
              className={relationScope === "all" ? "active" : ""}
              onClick={() => setRelationScope("all")}
            >
              전체 관계
            </button>
          </div>
          {ENTITY_TYPES.map((type) => (
            <button
              key={type}
              className={visibleTypes.has(type) ? `active entity-${type}` : ""}
              onClick={() => toggleEntityType(type)}
            >
              {ENTITY_TYPE_LABELS[type]}
            </button>
          ))}
        </div>
        <GraphView
          graph={filteredGraph}
          selectedEntityId={selectedEntity?.id ?? null}
          onSelectEntity={setSelectedEntity}
        />
      </main>
      <Inspector
        entity={selectedEntity}
        issues={openIssues}
        evidenceByIssueId={evidenceByIssueId}
        onIssueStatus={updateIssueStatus}
      />
      {projectModalOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setProjectModalOpen(false)}>
          <form
            className="modal"
            onSubmit={submitNewProject}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div>
              <span className="label">새 작품</span>
              <h2>작품 이름 설정</h2>
            </div>
            <label htmlFor="new-project-title">작품 제목</label>
            <input
              id="new-project-title"
              autoFocus
              maxLength={120}
              value={newProjectTitle}
              placeholder="예: 유리왕관의 항로"
              onChange={(event) => setNewProjectTitle(event.target.value)}
            />
            <div className="modal-actions">
              <button type="button" onClick={() => setProjectModalOpen(false)}>
                취소
              </button>
              <button type="submit">생성</button>
            </div>
          </form>
        </div>
      )}
      {documentPathModalOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={() => setDocumentPathModalOpen(false)}
        >
          <form
            className="modal"
            onSubmit={submitDocumentPath}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div>
              <span className="label">원고 추가</span>
              <h2>파일 경로 입력</h2>
            </div>
            <label htmlFor="document-path">원고 파일 경로</label>
            <input
              id="document-path"
              autoFocus
              value={documentPathDraft}
              placeholder="/Users/name/Documents/story.md"
              onChange={(event) => setDocumentPathDraft(event.target.value)}
            />
            <div className="modal-actions">
              <button type="button" onClick={() => setDocumentPathModalOpen(false)}>
                취소
              </button>
              <button type="submit">추가</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
