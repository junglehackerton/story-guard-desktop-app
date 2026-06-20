import cytoscape, { Core } from "cytoscape";
import { Maximize2, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { buildOrganizationMembership, isMembershipRelation } from "../lib/graphMembership";
import {
  clearGraphPositions,
  readGraphPositions,
  type GraphPosition,
  writeGraphPositions,
} from "../lib/graphLayoutStorage";
import type { EntityNode, EntityType, GraphPayload, RelationEdge } from "../lib/types";

const ENTITY_COLORS: Record<string, { fill: string; border: string }> = {
  character: { fill: "#7163c6", border: "#4c3fa2" },
  place: { fill: "#5f9075", border: "#3f6f56" },
  organization: { fill: "#a85b68", border: "#813f4c" },
  item: { fill: "#b78343", border: "#8a602c" },
  event: { fill: "#8a6aa9", border: "#684b88" },
  rule: { fill: "#4d8b87", border: "#2f6865" },
  foreshadowing: { fill: "#6687bd", border: "#46679a" },
};

const GRAPH_LAYOUT: cytoscape.LayoutOptions = {
  name: "preset",
  animate: false,
  fit: true,
  padding: 96,
};

export const MEMBERSHIP_EDGE_STYLE = {
  opacity: 0.48,
  "text-opacity": 0,
  "line-style": "dotted",
  width: 2.1,
  "z-index": 6,
} as const;

const ENTITY_TYPE_ORDER: EntityType[] = [
  "character",
  "place",
  "organization",
  "item",
  "event",
  "rule",
  "foreshadowing",
];
interface GraphViewProps {
  projectId: number | null;
  graph: GraphPayload;
  selectedEntityId: number | null;
  onSelectEntity: (entity: EntityNode | null) => void;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function mixHex(from: string, to: string, amount: number) {
  const parse = (value: string) => {
    const normalized = value.replace("#", "");
    return [
      Number.parseInt(normalized.slice(0, 2), 16),
      Number.parseInt(normalized.slice(2, 4), 16),
      Number.parseInt(normalized.slice(4, 6), 16),
    ];
  };
  const [r1, g1, b1] = parse(from);
  const [r2, g2, b2] = parse(to);
  const channel = (a: number, b: number) => Math.round(a + (b - a) * amount);
  return `#${[channel(r1, r2), channel(g1, g2), channel(b1, b2)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("")}`;
}

function shortRelationLabel(label: string) {
  return label.length > 12 ? `${label.slice(0, 11)}...` : label;
}

function shortEntityLabel(label: string) {
  return label.length > 14 ? `${label.slice(0, 13)}...` : label;
}

function entityVisual(entity: EntityNode, degree: number, clusterSize: number) {
  const palette = ENTITY_COLORS[entity.type] ?? { fill: "#7a8494", border: "#596272" };
  const weight = clamp(
    entity.type === "organization" ? Math.max(entity.visual_weight ?? 0.5, 0.72) : (entity.visual_weight ?? 0.5),
    0.22,
    1,
  );
  const livelyFill = mixHex("#efe6d8", palette.fill, weight);
  const fill =
    entity.appearance_state === "dormant"
      ? mixHex(livelyFill, "#d6cdc0", 0.62)
      : entity.appearance_state === "new"
        ? mixHex(livelyFill, "#c78635", 0.24)
        : entity.appearance_state === "fading"
          ? mixHex(livelyFill, "#b7aa9b", 0.35)
          : livelyFill;
  const border =
    entity.appearance_state === "new"
      ? "#a95f1d"
      : entity.appearance_state === "dormant"
        ? "#8b8278"
        : palette.border;
  return {
    fill,
    border,
    opacity: entity.appearance_state === "dormant" ? 0.5 : entity.appearance_state === "fading" ? 0.72 : 1,
    size:
      30 +
      weight * 24 +
      Math.min(degree * 1.6, 10) +
      (entity.type === "organization" ? 14 + Math.min(clusterSize * 3.8, 34) : 0),
    weight,
  };
}

function relationTone(label: string) {
  const normalized = label.toLowerCase();
  if (/적대|대립|배신|의심|충돌|enemy|hostile|oppos|conflict|betray|rival/.test(normalized)) {
    return "#a45353";
  }
  if (/동맹|친구|협력|보호|구함|ally|friend|protect|support|trust/.test(normalized)) {
    return "#54785d";
  }
  if (/소속|조직|대표|관할|산하|휘하|본부|거점|member|leader|works|belongs|contains|affiliated|under/.test(normalized)) {
    return "#626b90";
  }
  if (/소유|아이템|사용|가지|열쇠|own|has|uses|item|possess/.test(normalized)) {
    return "#98713f";
  }
  if (/장소|발견|열림|있|located|visits|appears|at |in /.test(normalized)) {
    return "#4f817d";
  }
  if (/규칙|룰|rule|세계/.test(normalized)) {
    return "#4d8b87";
  }
  if (/떡밥|복선|foreshadow/.test(normalized)) {
    return "#6687bd";
  }
  return "#8790a0";
}

function sortedEntities(
  entities: EntityNode[],
  degreeByEntityId: Map<number, number>,
) {
  return [...entities].sort((left, right) => {
    const typeDelta = ENTITY_TYPE_ORDER.indexOf(left.type) - ENTITY_TYPE_ORDER.indexOf(right.type);
    if (typeDelta !== 0) {
      return typeDelta;
    }
    const degreeDelta = (degreeByEntityId.get(right.id) ?? 0) - (degreeByEntityId.get(left.id) ?? 0);
    if (degreeDelta !== 0) {
      return degreeDelta;
    }
    return left.name.localeCompare(right.name, "ko");
  });
}

export function buildObsidianPositions(
  graph: GraphPayload,
  entitiesById: Map<number, EntityNode>,
  membershipByOrganizationId: Map<number, Set<number>>,
  parentOrganizationByEntityId: Map<number, number>,
  degreeByEntityId: Map<number, number>,
) {
  const positions = new Map<number, GraphPosition>();
  const assignedEntityIds = new Set<number>();
  const organizations = sortedEntities(
    graph.entities.filter((entity) => entity.type === "organization"),
    degreeByEntityId,
  ).sort(
    (left, right) =>
      (membershipByOrganizationId.get(right.id)?.size ?? 0) -
        (membershipByOrganizationId.get(left.id)?.size ?? 0) ||
      (degreeByEntityId.get(right.id) ?? 0) - (degreeByEntityId.get(left.id) ?? 0),
  );

  const organizationDomains = organizations.map((organization) => {
    const memberIds = membershipByOrganizationId.get(organization.id) ?? new Set();
    const memberEntities = sortedEntities(
      [...memberIds]
        .map((entityId) => entitiesById.get(entityId))
        .filter((entity): entity is EntityNode => Boolean(entity)),
      degreeByEntityId,
    );
    const columnCount = clamp(Math.ceil(Math.sqrt(Math.max(memberEntities.length, 1) * 1.28)), 2, 5);
    const rowCount = Math.max(1, Math.ceil(memberEntities.length / columnCount));
    return {
      organization,
      memberEntities,
      columnCount,
      rowCount,
      width: Math.max(500, columnCount * 168 + 210),
      height: Math.max(340, rowCount * 124 + 210),
    };
  });

  const domainsPerRow = organizations.length <= 1 ? 1 : 2;
  const rowGap = 260;
  const columnGap = 260;
  let cursorY = 0;

  for (let rowStart = 0; rowStart < organizationDomains.length; rowStart += domainsPerRow) {
    const rowDomains = organizationDomains.slice(rowStart, rowStart + domainsPerRow);
    const rowWidth =
      rowDomains.reduce((sum, domain) => sum + domain.width, 0) +
      Math.max(0, rowDomains.length - 1) * columnGap;
    const rowHeight = Math.max(...rowDomains.map((domain) => domain.height), 0);
    let cursorX = -rowWidth / 2;

    for (const domain of rowDomains) {
      const { organization, memberEntities, columnCount } = domain;
      const hasMembers = memberEntities.length > 0;
      const center = {
        x: cursorX + domain.width / 2,
        y: cursorY + domain.height / 2,
      };
      cursorX += domain.width + columnGap;

      if (!hasMembers || parentOrganizationByEntityId.has(organization.id)) {
        positions.set(organization.id, center);
      }
      assignedEntityIds.add(organization.id);

      const cellWidth = 168;
      const cellHeight = 124;
      const gridWidth = (columnCount - 1) * cellWidth;
      const gridHeight = (Math.max(1, Math.ceil(memberEntities.length / columnCount)) - 1) * cellHeight;
      const arcLift = Math.min(58, Math.max(0, memberEntities.length - 2) * 7);

      memberEntities.forEach((member, memberIndex) => {
        const column = memberIndex % columnCount;
        const row = Math.floor(memberIndex / columnCount);
        const rowOffset =
          columnCount > 2 && row % 2 === 1 ? Math.min(44, cellWidth / 4) : 0;
        const normalizedColumn =
          columnCount === 1 ? 0 : (column - (columnCount - 1) / 2) / ((columnCount - 1) / 2);
        const arcY = Math.abs(normalizedColumn) * arcLift;
        positions.set(member.id, {
          x: center.x - gridWidth / 2 + column * cellWidth + rowOffset,
          y: center.y - gridHeight / 2 + row * cellHeight + arcY,
        });
        assignedEntityIds.add(member.id);
      });
    }

    cursorY += rowHeight + rowGap;
  }

  const organizationAreaHeight =
    organizationDomains.length > 0 ? cursorY - rowGap : 0;
  const organizationCenterOffset = organizationAreaHeight > 0 ? organizationAreaHeight / 2 : 0;
  for (const [entityId, position] of positions) {
    positions.set(entityId, {
      x: position.x,
      y: position.y - organizationCenterOffset,
    });
  }

  organizations.forEach((organization) => {
    assignedEntityIds.add(organization.id);
  });

  const standaloneOrganizations = organizations.filter(
    (organization) => (membershipByOrganizationId.get(organization.id)?.size ?? 0) === 0,
  );
  standaloneOrganizations.forEach((organization, index) => {
    if (!positions.has(organization.id)) {
      positions.set(organization.id, {
        x: (index - (standaloneOrganizations.length - 1) / 2) * 260,
        y: organizationDomains.length > 0 ? organizationAreaHeight / 2 + 160 : -80,
      });
    }
  });

  /*
   * Unassigned nodes are kept below organization domains by type lanes. They are intentionally
   * far from the organization rows so cross-links stay readable instead of stacking at center.
   */
  const looseEntities = sortedEntities(
    graph.entities.filter((entity) => !assignedEntityIds.has(entity.id)),
    degreeByEntityId,
  );
  const entitiesByType = new Map<EntityType, EntityNode[]>();
  for (const entity of looseEntities) {
    entitiesByType.set(entity.type, [...(entitiesByType.get(entity.type) ?? []), entity]);
  }
  const activeTypes = ENTITY_TYPE_ORDER.filter((type) => entitiesByType.has(type));
  const laneGap = 260;
  const startY = organizationDomains.length > 0 ? organizationAreaHeight / 2 + 300 : -150;
  activeTypes.forEach((type, laneIndex) => {
    const laneEntities = entitiesByType.get(type) ?? [];
    const laneX = (laneIndex - (activeTypes.length - 1) / 2) * laneGap;
    laneEntities.forEach((entity, index) => {
      positions.set(entity.id, {
        x: laneX + (index % 2 === 0 ? -34 : 34),
        y: startY + Math.floor(index / 2) * 118,
      });
    });
  });

  return positions;
}

function mergePositions(
  autoPositions: Map<number, GraphPosition>,
  savedPositions: Map<number, GraphPosition>,
) {
  const merged = new Map(autoPositions);
  for (const [entityId, position] of savedPositions) {
    if (merged.has(entityId)) {
      merged.set(entityId, position);
    }
  }
  return merged;
}

function collectCurrentNodePositions(cy: Core) {
  const positions = new Map<number, GraphPosition>();
  cy.nodes().forEach((node) => {
    if (node.data("isContainer") === "yes") {
      return;
    }
    const rawId = String(node.id()).replace("entity-", "");
    const entityId = Number(rawId);
    if (!Number.isFinite(entityId)) {
      return;
    }
    const position = node.position();
    positions.set(entityId, { x: position.x, y: position.y });
  });
  return positions;
}

export function GraphView({ projectId, graph, selectedEntityId, onSelectEntity }: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const [zoomLabel, setZoomLabel] = useState("100%");
  const [layoutResetNonce, setLayoutResetNonce] = useState(0);
  const entitiesById = useMemo(
    () => new Map(graph.entities.map((entity) => [entity.id, entity])),
    [graph.entities],
  );

  const degreeByEntityId = useMemo(() => {
    const degrees = new Map<number, number>();
    for (const entity of graph.entities) {
      degrees.set(entity.id, 0);
    }
    for (const relation of graph.relations) {
      degrees.set(relation.source_entity_id, (degrees.get(relation.source_entity_id) ?? 0) + 1);
      degrees.set(relation.target_entity_id, (degrees.get(relation.target_entity_id) ?? 0) + 1);
    }
    return degrees;
  }, [graph.entities, graph.relations]);

  const { membershipByOrganizationId, parentOrganizationByEntityId } = useMemo(
    () => buildOrganizationMembership(graph, entitiesById),
    [entitiesById, graph],
  );

  const autoNodePositions = useMemo(
    () =>
      buildObsidianPositions(
        graph,
        entitiesById,
        membershipByOrganizationId,
        parentOrganizationByEntityId,
        degreeByEntityId,
      ),
    [degreeByEntityId, entitiesById, graph, membershipByOrganizationId, parentOrganizationByEntityId],
  );

  const savedNodePositions = useMemo(
    () => readGraphPositions(projectId, graph.entities),
    [graph.entities, layoutResetNonce, projectId],
  );

  const nodePositions = useMemo(
    () => mergePositions(autoNodePositions, savedNodePositions),
    [autoNodePositions, savedNodePositions],
  );

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    let cancelled = false;
    let layout: cytoscape.Layouts | null = null;
    let mountedCy: Core | null = null;
    const frameId = window.requestAnimationFrame(() => {
      if (cancelled || !containerRef.current) {
        return;
      }
      const elements = [
        ...graph.entities.map((entity) => {
          const clusterSize = membershipByOrganizationId.get(entity.id)?.size ?? 0;
          const parentOrganizationId = parentOrganizationByEntityId.get(entity.id);
          const isContainer = entity.type === "organization" && clusterSize > 0;
          const visual = entityVisual(
            entity,
            degreeByEntityId.get(entity.id) ?? 0,
            clusterSize,
          );
          return {
            data: {
              id: `entity-${entity.id}`,
              parent: parentOrganizationId ? `entity-${parentOrganizationId}` : undefined,
              label: shortEntityLabel(entity.name),
              fullLabel: entity.name,
              type: entity.type,
              isContainer: isContainer ? "yes" : "no",
              isMember: parentOrganizationId ? "yes" : "no",
              state: entity.appearance_state,
              fill: visual.fill,
              border: visual.border,
              opacity: visual.opacity,
              size: visual.size,
              weight: visual.weight,
              clusterSize,
            },
            position: isContainer ? undefined : nodePositions.get(entity.id),
          };
        }),
        ...graph.relations.map((relation) => {
          const membership = isMembershipRelation(relation);
          const displayLabel = relation.display_label || (relation.type === "co_occurs" ? "" : relation.type);
          const isWeak = relation.is_weak || relation.type === "co_occurs";
          const strength = clamp(relation.strength ?? relation.confidence ?? 0.55, 0.05, 1);
          return {
            data: {
              id: `relation-${relation.id}`,
              source: `entity-${relation.source_entity_id}`,
              target: `entity-${relation.target_entity_id}`,
              label: relation.type,
              displayLabel: membership ? "" : displayLabel ? shortRelationLabel(displayLabel) : "",
              confidence: clamp(relation.confidence ?? 0.55, 0.05, 1),
              strength,
              weak: isWeak,
              color: relationTone(relation.type),
              arrowShape: isWeak || membership ? "none" : "triangle",
              lineStyle: relation.is_recent ? "solid" : "dashed",
              aggregate: relation.id < 0 ? "yes" : "no",
              relationKind: membership ? "membership" : "normal",
            },
          };
        }),
      ];

      if (cyRef.current) {
        cyRef.current.stop(true, true);
        cyRef.current.elements().stop(true, true);
        cyRef.current.destroy();
        cyRef.current = null;
      }
      const cy = cytoscape({
        container: containerRef.current,
        elements,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(fill)",
              "border-color": "data(border)",
              "border-width": (element: cytoscape.NodeSingular) =>
                1.4 + Number(element.data("weight") ?? 0.2) * 2.2,
              opacity: (element: cytoscape.NodeSingular) => Number(element.data("opacity") ?? 1),
              label: "data(label)",
              color: "#242936",
              "font-size": 12,
              "font-weight": 700,
              "text-valign": "bottom",
              "text-margin-y": 9,
              "text-background-color": "#f8f4ec",
              "text-background-opacity": 0.86,
              "text-background-padding": "3px",
              "text-border-color": "#eadfce",
              "text-border-opacity": 0.65,
              "text-border-width": 1,
              width: "data(size)",
              height: "data(size)",
              "z-index": 12,
              "overlay-opacity": 0,
            },
          },
          {
            selector: "node[state = 'new']",
            style: {
              "border-width": 4,
              "underlay-color": "#c78635",
              "underlay-padding": 6,
              "underlay-opacity": 0.16,
            },
          },
          {
            selector: "node[type = 'organization']",
            style: {
              shape: "round-rectangle",
              color: "#fffdf8",
              "font-size": 13,
              "font-weight": 800,
              "text-valign": "center",
              "text-margin-y": 0,
              "text-background-opacity": 0,
              "text-border-opacity": 0,
            },
          },
          {
            selector: "node[isContainer = 'yes']",
            style: {
              shape: "round-rectangle",
              "background-opacity": 0.14,
              "border-width": 2.4,
              "border-style": "solid",
              color: "data(border)",
              "font-size": 15,
              "font-weight": 800,
              "text-valign": "top",
              "text-halign": "center",
              "text-margin-y": -18,
              "text-background-color": "#fffdf8",
              "text-background-opacity": 0.9,
              "text-background-padding": "5px",
              "text-border-color": "#eadfce",
              "text-border-opacity": 0.8,
              "text-border-width": 1,
              padding: "68px",
              "z-index": 1,
            },
          },
          {
            selector: "node[isMember = 'yes']",
            style: {
              "z-index": 18,
              "text-background-opacity": 0.94,
            },
          },
          {
            selector: "node:selected",
            style: {
              "border-width": 4,
              "border-color": "#2a241f",
              "underlay-color": "#6b5b49",
              "underlay-padding": 9,
              "underlay-opacity": 0.2,
              "underlay-shape": "ellipse",
            },
          },
          {
            selector: "edge",
            style: {
              width: (element: cytoscape.EdgeSingular) =>
                0.8 + Number(element.data("strength") ?? 0.55) * 3.7,
              opacity: (element: cytoscape.EdgeSingular) =>
                element.data("weak")
                  ? 0.16
                  : 0.24 + Number(element.data("strength") ?? 0.55) * 0.55,
              label: "data(displayLabel)",
              color: "#5f6470",
              "font-size": 9,
              "font-weight": 600,
              "text-opacity": 0,
              "text-rotation": "autorotate",
              "text-margin-y": -8,
              "text-background-color": "#f8f4ec",
              "text-background-opacity": 0.72,
              "text-background-padding": "2px",
              "line-color": (element: cytoscape.EdgeSingular) => element.data("color"),
              "target-arrow-color": (element: cytoscape.EdgeSingular) => element.data("color"),
              "target-arrow-shape": (element: cytoscape.EdgeSingular): "triangle" | "none" =>
                element.data("arrowShape") === "triangle" ? "triangle" : "none",
              "line-style": (element: cytoscape.EdgeSingular): "solid" | "dashed" =>
                element.data("lineStyle") === "dashed" ? "dashed" : "solid",
              "curve-style": "bezier",
              "control-point-step-size": 42,
            },
          },
          {
            selector: "edge[relationKind = 'membership']",
            style: MEMBERSHIP_EDGE_STYLE,
          },
          {
            selector: "edge[aggregate = 'yes']",
            style: {
              width: (element: cytoscape.EdgeSingular) =>
                2.4 + Number(element.data("strength") ?? 0.55) * 4.4,
              opacity: 0.88,
              "text-opacity": 0.9,
              "line-style": "solid",
              "z-index": 8,
            },
          },
          {
            selector: ".dimmed",
            style: {
              opacity: 0.12,
              "text-opacity": 0.1,
            },
          },
          {
            selector: "edge.hover, edge.spotlight",
            style: {
              opacity: 0.95,
              "text-opacity": 1,
              "z-index": 10,
            },
          },
          {
            selector: "node.spotlight",
            style: {
              opacity: 1,
              "border-width": 4,
              "z-index": 20,
            },
          },
        ],
        layout: { name: "preset" },
        maxZoom: 2.6,
        minZoom: 0.25,
      });

      const updateZoomLabel = () => setZoomLabel(`${Math.round(cy.zoom() * 100)}%`);
      cy.on("zoom", updateZoomLabel);
      cy.ready(updateZoomLabel);
      cy.on("tap", "node", (event) => {
        const rawId = String(event.target.id()).replace("entity-", "");
        onSelectEntity(entitiesById.get(Number(rawId)) ?? null);
      });
      cy.on("tap", (event) => {
        if (event.target === cy) {
          onSelectEntity(null);
        }
      });
      cy.on("dragfree", "node", () => {
        writeGraphPositions(projectId, collectCurrentNodePositions(cy));
      });
      cy.on("mouseover", "edge", (event) => event.target.addClass("hover"));
      cy.on("mouseout", "edge", (event) => event.target.removeClass("hover"));

      cyRef.current = cy;
      mountedCy = cy;
      layout = cy.layout(GRAPH_LAYOUT);
      layout.run();
      applyFocus(cy, selectedEntityId);
      if (selectedEntityId !== null) {
        cy.$id(`entity-${selectedEntityId}`).select();
      }
    });

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frameId);
      layout?.stop();
      if (mountedCy) {
        mountedCy.stop(true, true);
        mountedCy.elements().stop(true, true);
        mountedCy.destroy();
        if (cyRef.current === mountedCy) {
          cyRef.current = null;
        }
      }
    };
  }, [
    degreeByEntityId,
    entitiesById,
    graph,
    membershipByOrganizationId,
    nodePositions,
    onSelectEntity,
    parentOrganizationByEntityId,
    projectId,
  ]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    cy.nodes().unselect();
    applyFocus(cy, selectedEntityId);
    if (selectedEntityId !== null) {
      cy.$id(`entity-${selectedEntityId}`).select();
    }
  }, [selectedEntityId]);

  const zoomGraph = useCallback((factor: number) => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    const container = cy.container();
    const level = clamp(cy.zoom() * factor, cy.minZoom(), cy.maxZoom());
    cy.animate(
      {
        zoom: {
          level,
          renderedPosition: {
            x: (container?.clientWidth ?? 0) / 2,
            y: (container?.clientHeight ?? 0) / 2,
          },
        },
      },
      { duration: 180, easing: "ease-out-cubic" },
    );
  }, []);

  const fitGraph = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    cy.animate({ fit: { eles: cy.elements(), padding: 112 } }, { duration: 180, easing: "ease-out-cubic" });
    applyFocus(cy, selectedEntityId);
  }, [selectedEntityId]);

  const resetGraphLayout = useCallback(() => {
    clearGraphPositions(projectId);
    setLayoutResetNonce((current) => current + 1);
  }, [projectId]);

  if (graph.entities.length === 0) {
    return (
      <div className="empty-graph">
        <h2>아직 그래프가 없습니다</h2>
        <p>원고를 추가한 뒤 분석을 실행하면 인물, 장소, 조직, 아이템, 떡밥 관계가 표시됩니다.</p>
      </div>
    );
  }

  return (
    <div className="graph-stage">
      <div ref={containerRef} className="graph-canvas" />
      <div className="graph-hud" aria-label="그래프 확대 축소">
        <button type="button" onClick={() => zoomGraph(1.18)} title="확대">
          <ZoomIn size={16} />
        </button>
        <span>{zoomLabel}</span>
        <button type="button" onClick={() => zoomGraph(0.84)} title="축소">
          <ZoomOut size={16} />
        </button>
        <button type="button" onClick={fitGraph} title="그래프 맞춤">
          <Maximize2 size={16} />
        </button>
        <button type="button" onClick={resetGraphLayout} title="자동 배치로 초기화">
          <RotateCcw size={16} />
        </button>
      </div>
    </div>
  );
}

function applyFocus(cy: Core, selectedEntityId: number | null) {
  cy.elements().removeClass("dimmed spotlight");
  if (selectedEntityId === null) {
    return;
  }
  const selected = cy.$id(`entity-${selectedEntityId}`);
  if (selected.empty()) {
    return;
  }
  const connectedEdges = selected.connectedEdges();
  const connectedNodes = connectedEdges.connectedNodes();
  const parent = selected.parent();
  const children = selected.descendants();
  const siblings = parent.length > 0 ? parent.children() : cy.collection();
  const focusNodes = selected.union(connectedNodes).union(parent).union(children).union(siblings);
  const focusEdges = connectedEdges.union(focusNodes.connectedEdges());
  cy.elements().addClass("dimmed");
  focusNodes.removeClass("dimmed").addClass("spotlight");
  focusEdges.removeClass("dimmed").addClass("spotlight");
}
