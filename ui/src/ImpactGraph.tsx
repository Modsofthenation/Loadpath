import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { typeLabel, wrapHint } from "./format";
import {
  defaultDetail,
  defaultProjection,
  familyFor,
  visibleGraph,
  type GraphDetail,
  type GraphFamily,
  type GraphProjection,
} from "./graphView";
import { inspectNode, type InspectorLink } from "./nodeInspector";
import {
  GRAPH_NODE_HEIGHT,
  GRAPH_NODE_WIDTH,
  layoutNodes,
  type GraphEdge,
  type GraphNode,
} from "./types";

const NO_NEIGHBORS = new Set<string>();

const LayeredGraph3D = lazy(() =>
  import("./LayeredGraph3D").then((mod) => ({ default: mod.LayeredGraph3D })),
);

const WEIGHT_COLOR: Record<string, string> = {
  cheap: "var(--edge-cheap)",
  expensive: "var(--edge-expensive)",
  critical: "var(--edge-critical)",
};

function LoadNode({ data, selected }: { data: { name: string; type: string }; selected?: boolean }) {
  return (
    <div className={selected ? "lp-node selected" : "lp-node"}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="t">{typeLabel(data.type)}</div>
      <div className="n" title={data.name}>
        {data.name}
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}

const nodeTypes = { load: LoadNode };
const ALL_FAMILIES = new Set<GraphFamily>(["django", "react", "stitch", "arch"]);

function FitViewOnTopology({ topologyKey }: { topologyKey: string }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => {
        fitView({ padding: 0.2, maxZoom: 1.15 });
      });
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [fitView, topologyKey]);
  return null;
}

export function toReactFlowElements(
  nodes: GraphNode[],
  edges: GraphEdge[],
  selectedId: string | null = null,
): { rfNodes: Node[]; rfEdges: Edge[] } {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const pos = layoutNodes(nodes, edges);
  const rfNodes: Node[] = nodes.map((n) => ({
    id: n.id,
    type: "load",
    position: pos.get(n.id) ?? { x: 0, y: 0 },
    data: { name: n.name, type: n.type, file: n.file_path },
    selected: selectedId === n.id,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    width: GRAPH_NODE_WIDTH,
    height: GRAPH_NODE_HEIGHT,
    style: { width: GRAPH_NODE_WIDTH, height: GRAPH_NODE_HEIGHT },
  }));
  const rfEdges: Edge[] = edges
    .filter((e) => byId.has(e.src) && byId.has(e.dst))
    .map((e) => {
      const stroke = WEIGHT_COLOR[e.weight] || "var(--edge-cheap)";
      const labeled = Boolean(selectedId && (e.src === selectedId || e.dst === selectedId));
      return {
        id: e.id,
        source: e.src,
        target: e.dst,
        type: "smoothstep",
        animated: e.weight === "critical",
        style: {
          stroke,
          strokeWidth: e.weight === "critical" ? 2.4 : 1.2,
          strokeDasharray: e.confidence < 0.8 ? "6 4" : undefined,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color: stroke,
        },
        label: labeled ? e.type.replaceAll("_", " ") : undefined,
        labelStyle: labeled ? { fill: "var(--ink)", fontSize: 10, fontWeight: 600 } : undefined,
        labelBgStyle: labeled ? { fill: "var(--graph-bg)", fillOpacity: 0.92 } : undefined,
        labelBgPadding: labeled ? ([3, 5] as [number, number]) : undefined,
        labelBgBorderRadius: labeled ? 4 : undefined,
      };
    });
  return { rfNodes, rfEdges };
}

function GraphInspector({
  node,
  nodes,
  edges,
  onClose,
}: {
  node: GraphNode;
  nodes: GraphNode[];
  edges: GraphEdge[];
  onClose: () => void;
}) {
  const info = inspectNode(node, nodes, edges);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <aside className="inspector" data-testid="graph-inspector">
      <div className="inspector-head">
        <div className="t">{info.typeLabel}</div>
        <div className="inspector-roles">
          {info.roles.map((role) => (
            <span key={role} className="inspector-chip">
              {role}
            </span>
          ))}
        </div>
        <button
          type="button"
          className="inspector-close"
          data-testid="graph-inspector-close"
          aria-label="Close inspector"
          onClick={onClose}
        >
          ×
        </button>
      </div>
      <div className="n">{wrapHint(info.name)}</div>
      <p className="inspector-purpose" data-testid="graph-inspector-purpose">
        {info.purpose}
      </p>
      {info.context ? <div className="muted">{wrapHint(info.context)}</div> : null}
      {info.file ? <div className="file">{wrapHint(info.file)}</div> : null}
      <div className="muted">{wrapHint(info.qualifiedName)}</div>
      <div className="muted inspector-layer">layer · {info.layer}</div>
      {info.facts.length ? (
        <dl className="inspector-facts" data-testid="graph-inspector-facts">
          {info.facts.map((fact) => (
            <div key={fact.key} className="inspector-fact">
              <dt>{fact.label}</dt>
              <dd>{wrapHint(fact.value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <InspectorLinks
        title="Inputs"
        testId="graph-inspector-inputs"
        links={info.inputs}
        extra={info.extraInputs}
        empty="Nothing in this graph points here."
      />
      <InspectorLinks
        title="Outputs"
        testId="graph-inspector-outputs"
        links={info.outputs}
        extra={info.extraOutputs}
        empty="This node does not point at anything in this graph."
      />
    </aside>
  );
}

function InspectorLinks({
  title,
  testId,
  links,
  extra,
  empty,
}: {
  title: string;
  testId: string;
  links: InspectorLink[];
  extra: number;
  empty: string;
}) {
  return (
    <section className="inspector-section" data-testid={testId}>
      <h3>
        {title}
        <span className="count">{links.length + extra}</span>
      </h3>
      {links.length ? (
        <ul>
          {links.map((link, i) => (
            <li key={`${link.edgeType}:${link.id}:${i}`}>
              <span className="inspector-link-name" title={link.name}>
                {wrapHint(link.name)}
              </span>
              <span className="inspector-link-meta">
                {link.typeLabel ? `${link.typeLabel} · ` : ""}
                {link.edgeLabel}
                {link.inferred ? " · inferred" : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">{empty}</p>
      )}
      {extra ? <p className="muted">+{extra} more</p> : null}
    </section>
  );
}

export function ImpactGraph({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [projection, setProjection] = useState<GraphProjection | null>(null);
  const [detail, setDetail] = useState<GraphDetail | null>(null);
  const [families, setFamilies] = useState<Set<GraphFamily>>(new Set(ALL_FAMILIES));
  const [neighborhoodOnly, setNeighborhoodOnly] = useState(false);
  const reduceMotion =
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const view = projection ?? defaultProjection(nodes.length);
  const level = detail ?? defaultDetail(nodes.length);
  const neighborhoodFocus = neighborhoodOnly && view === "3d" ? selectedId : null;
  const visible = useMemo(
    () =>
      visibleGraph(nodes, edges, {
        detail: level,
        families,
        focusId: neighborhoodFocus,
        neighborhoodOnly: Boolean(neighborhoodFocus),
      }),
    [nodes, edges, level, families, neighborhoodFocus],
  );
  const topologyKey = useMemo(
    () => `${visible.nodes.map((n) => n.id).join("\0")}|${visible.edges.map((e) => e.id).join("\0")}`,
    [visible.nodes, visible.edges],
  );
  const byId = useMemo(() => new Map(visible.nodes.map((n) => [n.id, n])), [visible.nodes]);
  const selected = selectedId ? byId.get(selectedId) ?? null : null;
  const { rfNodes, rfEdges } = useMemo(() => {
    const elements = toReactFlowElements(visible.nodes, visible.edges, selectedId);
    if (reduceMotion) {
      elements.rfEdges = elements.rfEdges.map((edge) => ({ ...edge, animated: false }));
    }
    return elements;
  }, [visible.nodes, visible.edges, selectedId, reduceMotion]);

  useEffect(() => {
    if (selectedId && !byId.has(selectedId)) setSelectedId(null);
  }, [byId, selectedId]);

  const onNodeClick: NodeMouseHandler = (_evt, node) => {
    setSelectedId(node.id);
  };

  const clearSelection = () => {
    setSelectedId(null);
    setNeighborhoodOnly(false);
  };

  const toggleFamily = (family: GraphFamily) => {
    setFamilies((current) => {
      const next = new Set(current);
      if (next.has(family)) {
        if (next.size === 1) return current;
        next.delete(family);
      } else {
        next.add(family);
      }
      return next;
    });
  };

  const presentFamilies = useMemo(() => {
    const found = new Set<GraphFamily>();
    for (const n of nodes) found.add(familyFor(n.type));
    return found;
  }, [nodes]);

  const hidden = nodes.length - visible.nodes.length;

  return (
    <div className="impact-graph" style={{ flex: 1, minHeight: 0, position: "relative", display: "flex", flexDirection: "column" }}>
      <div className="graph-toolbar" data-testid="graph-toolbar">
        <div className="seg" aria-label="Graph projection">
          <button
            type="button"
            data-testid="graph-view-2d"
            className={view === "2d" ? "active" : ""}
            aria-pressed={view === "2d"}
            onClick={() => setProjection("2d")}
          >
            2D map
          </button>
          <button
            type="button"
            data-testid="graph-view-3d"
            className={view === "3d" ? "active" : ""}
            aria-pressed={view === "3d"}
            onClick={() => setProjection("3d")}
          >
            3D layers
          </button>
        </div>
        <div className="seg" aria-label="Graph detail">
          <button
            type="button"
            data-testid="graph-detail-overview"
            className={level === "overview" ? "active" : ""}
            aria-pressed={level === "overview"}
            onClick={() => setDetail("overview")}
          >
            Overview
          </button>
          <button
            type="button"
            data-testid="graph-detail-full"
            className={level === "full" ? "active" : ""}
            aria-pressed={level === "full"}
            onClick={() => setDetail("full")}
          >
            Full
          </button>
        </div>
        <div className="seg" aria-label="Graph families">
          {(["django", "stitch", "react"] as const)
            .filter((family) => presentFamilies.has(family))
            .map((family) => (
              <button
                key={family}
                type="button"
                data-testid={`graph-family-${family}`}
                className={families.has(family) ? "active" : ""}
                aria-pressed={families.has(family)}
                onClick={() => toggleFamily(family)}
              >
                {family}
              </button>
            ))}
        </div>
        {view === "3d" ? (
          <button
            type="button"
            className={neighborhoodOnly ? "chip-btn active" : "chip-btn"}
            data-testid="graph-neighborhood"
            disabled={!selectedId}
            onClick={() => setNeighborhoodOnly((v) => !v)}
          >
            {neighborhoodOnly ? "Neighborhood" : "Focus neighbors"}
          </button>
        ) : null}
        <span className="muted graph-count">
          {visible.nodes.length} nodes · {visible.edges.length} edges
          {hidden ? ` · ${hidden} hidden` : ""}
        </span>
      </div>
      <div className="graph-stage">
        {view === "3d" ? (
          <div className="graph-3d" data-testid="graph-3d">
            <p className="graph-3d-hint">
              Architecture layers are stacked in depth (Django → stitch → React). Drag to orbit, scroll to
              zoom, click a node to inspect it.
            </p>
            <Suspense fallback={<p className="muted graph-3d-hint">Loading 3D layers…</p>}>
              <LayeredGraph3D
                nodes={visible.nodes}
                edges={visible.edges}
                selectedId={selectedId}
                neighborIds={neighborhoodFocus ? visible.neighborIds : NO_NEIGHBORS}
                onSelect={(id) => {
                  setSelectedId(id);
                  if (!id) setNeighborhoodOnly(false);
                }}
              />
            </Suspense>
            {selected ? (
              <GraphInspector node={selected} nodes={nodes} edges={edges} onClose={clearSelection} />
            ) : null}
          </div>
        ) : (
          <ReactFlowProvider>
            <ReactFlow
              nodes={rfNodes}
              edges={rfEdges}
              nodeTypes={nodeTypes}
              fitView={false}
              minZoom={0.25}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable
              deleteKeyCode={null}
              onNodeClick={onNodeClick}
              onPaneClick={clearSelection}
              proOptions={{ hideAttribution: false }}
              data-testid="impact-graph"
            >
              <FitViewOnTopology topologyKey={topologyKey} />
              <Background />
              <MiniMap
                pannable
                zoomable
                ariaLabel="Impact graph overview"
                nodeColor="var(--muted)"
                nodeStrokeColor="transparent"
                nodeStrokeWidth={0}
                maskColor="rgba(0, 0, 0, 0.45)"
                maskStrokeColor="var(--accent)"
                maskStrokeWidth={1.4}
                bgColor="var(--graph-bg)"
                style={{ width: 184, height: 128 }}
              />
              <Controls />
            </ReactFlow>
            {selected ? (
              <GraphInspector node={selected} nodes={nodes} edges={edges} onClose={clearSelection} />
            ) : null}
          </ReactFlowProvider>
        )}
      </div>
    </div>
  );
}
