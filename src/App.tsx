import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { Check, Pencil, X } from "lucide-react";
import { api } from "./lib/api";
import { ensureDesktopBackend, isTauriRuntime } from "./lib/desktopBackend";
import { ENTITY_TYPE_LABELS } from "./lib/labels";
import type {
  EntityNode,
  EntityRelationshipDetail,
  EntityType,
  EnvironmentSetupProgress,
  EnvironmentStatus,
  EvidenceChunk,
  GraphPayload,
  IssueStatus,
  AppSettings,
  LocalAiHealth,
  Project,
  RelationEdge,
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
  generation_model: "qwen2.5-1.5b-instruct-q4_k_m.gguf",
  embedding_model: "qwen2.5-1.5b-instruct-q4_k_m.gguf",
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
const MEMBERSHIP_RELATION_PATTERN = /소속|조직|구성원|대표|멤버|member|leader|belongs|works/i;

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

function relationScore(relation: RelationEdge) {
  return relation.strength ?? relation.confidence ?? 0;
}

function isCoreRelation(relation: RelationEdge) {
  return !relation.is_weak && relation.type !== "co_occurs" && relation.confidence >= 0.68;
}

function relationName(relation: RelationEdge) {
  return relation.display_label || (relation.type === "co_occurs" ? "동시 등장" : relation.type);
}

function isMembershipRelation(relation: RelationEdge) {
  return MEMBERSHIP_RELATION_PATTERN.test(`${relation.type} ${relation.display_label}`);
}

function aggregateOrganizationRelations(graph: GraphPayload, scope: RelationScope): RelationEdge[] {
  const entitiesById = new Map(graph.entities.map((entity) => [entity.id, entity]));
  const organizationIds = new Set(
    graph.entities.filter((entity) => entity.type === "organization").map((entity) => entity.id),
  );
  if (organizationIds.size < 2) {
    return [];
  }

  const ownerOrganizationByEntityId = new Map<number, number>();
  for (const organizationId of organizationIds) {
    ownerOrganizationByEntityId.set(organizationId, organizationId);
  }

  for (const relation of graph.relations) {
    if (!isMembershipRelation(relation)) {
      continue;
    }
    const source = entitiesById.get(relation.source_entity_id);
    const target = entitiesById.get(relation.target_entity_id);
    if (!source || !target) {
      continue;
    }
    if (source.type === "organization" && target.type !== "organization") {
      ownerOrganizationByEntityId.set(target.id, source.id);
    }
    if (target.type === "organization" && source.type !== "organization") {
      ownerOrganizationByEntityId.set(source.id, target.id);
    }
  }

  const aggregateByPair = new Map<
    string,
    {
      sourceId: number;
      targetId: number;
      count: number;
      confidence: number;
      strength: number;
      isRecent: boolean;
      evidenceChunkIds: Set<number>;
    }
  >();

  for (const relation of graph.relations) {
    if (scope === "core" && !isCoreRelation(relation) && !isMembershipRelation(relation)) {
      continue;
    }
    const sourceOrganizationId = ownerOrganizationByEntityId.get(relation.source_entity_id);
    const targetOrganizationId = ownerOrganizationByEntityId.get(relation.target_entity_id);
    if (
      !sourceOrganizationId ||
      !targetOrganizationId ||
      sourceOrganizationId === targetOrganizationId
    ) {
      continue;
    }
    const [leftId, rightId] = [sourceOrganizationId, targetOrganizationId].sort((left, right) => left - right);
    const key = `${leftId}-${rightId}`;
    const current =
      aggregateByPair.get(key) ??
      {
        sourceId: leftId,
        targetId: rightId,
        count: 0,
        confidence: 0,
        strength: 0,
        isRecent: false,
        evidenceChunkIds: new Set<number>(),
      };
    current.count += 1;
    current.confidence = Math.max(current.confidence, relation.confidence ?? 0.55);
    current.strength = Math.max(current.strength, relationScore(relation));
    current.isRecent ||= relation.is_recent;
    for (const chunkId of relation.evidence_chunk_ids) {
      current.evidenceChunkIds.add(chunkId);
    }
    aggregateByPair.set(key, current);
  }

  let virtualId = -1;
  return [...aggregateByPair.values()].map((aggregate) => ({
    id: virtualId--,
    project_id: graph.entities[0]?.project_id ?? 0,
    source_entity_id: aggregate.sourceId,
    target_entity_id: aggregate.targetId,
    type: "조직 간접 관계",
    confidence: Math.min(0.95, Math.max(0.7, aggregate.confidence)),
    evidence_chunk_ids: [...aggregate.evidenceChunkIds].slice(0, 8),
    strength: Math.min(0.96, 0.48 + Math.log2(aggregate.count + 1) * 0.14 + aggregate.strength * 0.22),
    is_weak: false,
    is_recent: aggregate.isRecent,
    display_label: `하위 관계 ${aggregate.count}개`,
  }));
}

function buildRelationshipExplanation(
  entity: EntityNode,
  other: EntityNode,
  relation: RelationEdge,
  direction: EntityRelationshipDetail["direction"],
) {
  const sourceName = direction === "outgoing" ? entity.name : other.name;
  const targetName = direction === "outgoing" ? other.name : entity.name;
  const confidence = Math.round((relation.confidence ?? 0) * 100);
  const strength = Math.round(relationScore(relation) * 100);
  const recency = relation.is_recent ? "최근 원고에서도 유지" : "이전 원고 근거 중심";
  const evidenceCount = relation.evidence_chunk_ids.length;
  const evidence = evidenceCount > 0 ? `, 근거 chunk ${evidenceCount}개` : "";
  return `${sourceName} -> ${targetName}: ${relationName(relation)}. 신뢰도 ${confidence}%, 관계 강도 ${strength}%. ${recency}${evidence}.`;
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
  const [localAi, setLocalAi] = useState<LocalAiHealth | null>(null);
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
    const directRelations = graph.relations
      .filter(
        (relation) =>
          visibleIds.has(relation.source_entity_id) && visibleIds.has(relation.target_entity_id),
      )
      .filter(
        (relation) =>
          relationScope === "all" || isCoreRelation(relation) || isMembershipRelation(relation),
      );
    const organizationOnly =
      entities.length > 0 && [...visibleTypes].every((type) => type === "organization");
    const organizationRelations = organizationOnly ? aggregateOrganizationRelations(graph, relationScope) : [];
    const relations = [...directRelations, ...organizationRelations].filter(
      (relation) =>
        visibleIds.has(relation.source_entity_id) && visibleIds.has(relation.target_entity_id),
    );
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

  const selectedRelationshipDetails = useMemo<EntityRelationshipDetail[]>(() => {
    if (!selectedEntity) {
      return [];
    }
    const entitiesById = new Map(filteredGraph.entities.map((entity) => [entity.id, entity]));
    return filteredGraph.relations
      .filter(
        (relation) =>
          relation.source_entity_id === selectedEntity.id ||
          relation.target_entity_id === selectedEntity.id,
      )
      .map((relation) => {
        const direction = relation.source_entity_id === selectedEntity.id ? "outgoing" : "incoming";
        const otherEntityId =
          direction === "outgoing" ? relation.target_entity_id : relation.source_entity_id;
        const other = entitiesById.get(otherEntityId);
        if (!other) {
          return null;
        }
        return {
          relation,
          other,
          direction,
          explanation: buildRelationshipExplanation(selectedEntity, other, relation, direction),
        };
      })
      .filter((detail): detail is EntityRelationshipDetail => detail !== null)
      .sort((left, right) => relationScore(right.relation) - relationScore(left.relation))
      .slice(0, 12);
  }, [filteredGraph, selectedEntity]);

  const refreshLocalAi = useCallback(async () => {
    try {
      setLocalAi(await api.localAiHealth());
    } catch (error) {
      setLocalAi({
        ok: false,
        runtime: "story-guard-local",
        message: error instanceof Error ? error.message : "Local AI 상태 확인 실패",
        models: [],
        model_dir: "",
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
        refreshLocalAi(),
        refreshSettings(),
        refreshSetup(),
      ]);
      setNotice("준비 완료");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "백엔드 연결 실패");
    }
  }, [refreshLocalAi, refreshProjectData, refreshProjects, refreshSettings, refreshSetup]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    setProjectTitleDraft(selectedProject?.title ?? "");
    setEditingProjectTitle(false);
  }, [selectedProject?.id, selectedProject?.title]);

  useEffect(() => {
    if (
      selectedEntity &&
      !filteredGraph.entities.some((entity) => entity.id === selectedEntity.id)
    ) {
      setSelectedEntity(null);
    }
  }, [filteredGraph.entities, selectedEntity]);

  useEffect(() => {
    if (!setupProgress?.running) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void api.setupProgress().then(async (progress) => {
        setSetupProgress(progress);
        if (!progress.running) {
          await Promise.all([refreshSetup(), refreshLocalAi(), refreshSettings()]);
        }
      });
    }, 2000);
    return () => window.clearInterval(intervalId);
  }, [refreshLocalAi, refreshSettings, refreshSetup, setupProgress?.running]);

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
      setNotice(`생성 모델 저장: ${updated.generation_model}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "설정 저장 실패");
    }
  }

  async function startEnvironmentSetup() {
    try {
      setNotice("로컬 AI 모델을 준비합니다.");
      const progress = await api.runSetup({
        install_runtime: false,
        prepare_embedding_model: true,
        prepare_generation_model: true,
        embedding_model: setupStatus?.embedding_model ?? settings.embedding_model,
        generation_model:
          settings.generation_model ||
          setupStatus?.generation_model ||
          "qwen2.5-1.5b-instruct-q4_k_m.gguf",
      });
      setSetupProgress(progress);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "환경 설정 시작 실패");
    }
  }

  async function refreshEnvironmentSetup() {
    try {
      await Promise.all([refreshSetup(), refreshLocalAi(), refreshSettings()]);
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
        localAi={localAi}
        settings={settings}
        loading={loading}
        onCreateProject={createProject}
        onSelectProject={selectProject}
        onImportDocument={importDocument}
        onAnalyze={analyze}
        aiReady={setupStatus?.ready ?? false}
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
        relationships={selectedRelationshipDetails}
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
