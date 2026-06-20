import cytoscape, { Core } from "cytoscape";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  padding: 86,
};

const ENTITY_TYPE_ORDER: EntityType[] = [
  "character",
  "place",
  "organization",
  "item",
  "event",
  "rule",
  "foreshadowing",
];
const MEMBERSHIP_RELATION_PATTERN = /소속|조직|구성원|대표|멤버|member|leader|belongs|works/i;

type GraphPosition = { x: number; y: number };

interface GraphViewProps {
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
  if (/소속|조직|대표|member|leader|works|belongs/.test(normalized)) {
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

function isMembershipRelation(relation: RelationEdge) {
  return MEMBERSHIP_RELATION_PATTERN.test(`${relation.type} ${relation.display_label}`);
}

function buildOrganizationMembership(
  graph: GraphPayload,
  entitiesById: Map<number, EntityNode>,
) {
  const membershipByOrganizationId = new Map<number, Set<number>>();
  for (const entity of graph.entities) {
    if (entity.type === "organization") {
      membershipByOrganizationId.set(entity.id, new Set());
    }
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
      membershipByOrganizationId.get(source.id)?.add(target.id);
    }
    if (target.type === "organization" && source.type !== "organization") {
      membershipByOrganizationId.get(target.id)?.add(source.id);
    }
  }

  return { membershipByOrganizationId };
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

function buildObsidianPositions(
  graph: GraphPayload,
  entitiesById: Map<number, EntityNode>,
  membershipByOrganizationId: Map<number, Set<number>>,
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

  const hubGap = 360;
  const hubStartX = -((organizations.length - 1) * hubGap) / 2;
  organizations.forEach((organization, index) => {
    const hubPosition = {
      x: hubStartX + index * hubGap,
      y: index % 2 === 0 ? -60 : 36,
    };
    positions.set(organization.id, hubPosition);
    assignedEntityIds.add(organization.id);

    const memberEntities = sortedEntities(
      [...(membershipByOrganizationId.get(organization.id) ?? [])]
        .map((entityId) => entitiesById.get(entityId))
        .filter((entity): entity is EntityNode => Boolean(entity)),
      degreeByEntityId,
    );
    const radius = 118 + Math.min(memberEntities.length, 10) * 6;
    memberEntities.forEach((member, memberIndex) => {
      const angle = -Math.PI / 2 + (memberIndex / Math.max(memberEntities.length, 1)) * Math.PI * 2;
      const ringOffset = (memberIndex % 3) * 20;
      positions.set(member.id, {
        x: hubPosition.x + Math.cos(angle) * (radius + ringOffset),
        y: hubPosition.y + Math.sin(angle) * (radius + ringOffset),
      });
      assignedEntityIds.add(member.id);
    });
  });

  const looseEntities = sortedEntities(
    graph.entities.filter((entity) => !assignedEntityIds.has(entity.id)),
    degreeByEntityId,
  );
  const entitiesByType = new Map<EntityType, EntityNode[]>();
  for (const entity of looseEntities) {
    entitiesByType.set(entity.type, [...(entitiesByType.get(entity.type) ?? []), entity]);
  }
  const activeTypes = ENTITY_TYPE_ORDER.filter((type) => entitiesByType.has(type));
  const laneGap = 220;
  const startY = organizations.length > 0 ? 330 : -130;
  activeTypes.forEach((type, laneIndex) => {
    const laneEntities = entitiesByType.get(type) ?? [];
    const laneX = (laneIndex - (activeTypes.length - 1) / 2) * laneGap;
    laneEntities.forEach((entity, index) => {
      positions.set(entity.id, {
        x: laneX + (index % 2 === 0 ? -18 : 18),
        y: startY + Math.floor(index / 2) * 92,
      });
    });
  });

  return positions;
}

export function GraphView({ graph, selectedEntityId, onSelectEntity }: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const [zoomLabel, setZoomLabel] = useState("100%");
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

  const { membershipByOrganizationId } = useMemo(
    () => buildOrganizationMembership(graph, entitiesById),
    [entitiesById, graph],
  );

  const nodePositions = useMemo(
    () =>
      buildObsidianPositions(
        graph,
        entitiesById,
        membershipByOrganizationId,
        degreeByEntityId,
      ),
    [degreeByEntityId, entitiesById, graph, membershipByOrganizationId],
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
          const visual = entityVisual(
            entity,
            degreeByEntityId.get(entity.id) ?? 0,
            membershipByOrganizationId.get(entity.id)?.size ?? 0,
          );
          return {
            data: {
              id: `entity-${entity.id}`,
              label: shortEntityLabel(entity.name),
              fullLabel: entity.name,
              type: entity.type,
              state: entity.appearance_state,
              fill: visual.fill,
              border: visual.border,
              opacity: visual.opacity,
              size: visual.size,
              weight: visual.weight,
              clusterSize: membershipByOrganizationId.get(entity.id)?.size ?? 0,
            },
            position: nodePositions.get(entity.id),
          };
        }),
        ...graph.relations.map((relation) => {
          const displayLabel = relation.display_label || (relation.type === "co_occurs" ? "" : relation.type);
          const isWeak = relation.is_weak || relation.type === "co_occurs";
          const strength = clamp(relation.strength ?? relation.confidence ?? 0.55, 0.05, 1);
          return {
            data: {
              id: `relation-${relation.id}`,
              source: `entity-${relation.source_entity_id}`,
              target: `entity-${relation.target_entity_id}`,
              label: relation.type,
              displayLabel: displayLabel ? shortRelationLabel(displayLabel) : "",
              confidence: clamp(relation.confidence ?? 0.55, 0.05, 1),
              strength,
              weak: isWeak,
              color: relationTone(relation.type),
              arrowShape: isWeak ? "none" : "triangle",
              lineStyle: relation.is_recent ? "solid" : "dashed",
              aggregate: relation.id < 0 ? "yes" : "no",
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
              "font-weight": 850,
              "text-valign": "center",
              "text-margin-y": 0,
              "text-background-opacity": 0,
              "text-border-opacity": 0,
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
      cy.on("mouseover", "edge", (event) => event.target.addClass("hover"));
      cy.on("mouseout", "edge", (event) => event.target.removeClass("hover"));

      cyRef.current = cy;
      mountedCy = cy;
      layout = cy.layout(GRAPH_LAYOUT);
      layout.run();
      applyFocus(cy, selectedEntityId);
      if (selectedEntityId !== null) {
        cy.$id(`entity-${selectedEntityId}`).select();
        focusSelectedNode(cy, selectedEntityId);
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
  }, [degreeByEntityId, entitiesById, graph, membershipByOrganizationId, nodePositions, onSelectEntity]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    cy.nodes().unselect();
    applyFocus(cy, selectedEntityId);
    if (selectedEntityId !== null) {
      cy.$id(`entity-${selectedEntityId}`).select();
      focusSelectedNode(cy, selectedEntityId);
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
    cy.layout(GRAPH_LAYOUT).run();
    applyFocus(cy, selectedEntityId);
  }, [selectedEntityId]);

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
  cy.elements().addClass("dimmed");
  selected.removeClass("dimmed").addClass("spotlight");
  connectedNodes.removeClass("dimmed").addClass("spotlight");
  connectedEdges.removeClass("dimmed").addClass("spotlight");
}

function focusSelectedNode(cy: Core, selectedEntityId: number) {
  const selected = cy.$id(`entity-${selectedEntityId}`);
  if (selected.empty()) {
    return;
  }
  const neighborhood = selected.closedNeighborhood();
  if (neighborhood.nodes().length <= 1) {
    cy.animate({ fit: { eles: selected, padding: 140 } }, { duration: 220, easing: "ease-out-cubic" });
    return;
  }
  neighborhood
    .layout({
      name: "concentric",
      fit: true,
      padding: 108,
      animate: true,
      animationDuration: 240,
      minNodeSpacing: 58,
      concentric: (node: cytoscape.NodeSingular) => (node.id() === selected.id() ? 2 : 1),
      levelWidth: () => 1,
    })
    .run();
}
