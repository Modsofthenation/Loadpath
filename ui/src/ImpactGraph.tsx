import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  Background,
  BaseEdge,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getSmoothStepPath,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { typeLabel, wrapHint } from "./format";
import {
  defaultDetail,
  defaultProjection,
  familyFor,
  isolatePathIds,
  searchNodes,
  visibleGraph,
  type GraphDetail,
  type GraphFamily,
  type GraphProjection,
} from "./graphView";
import { inspectNode, type InspectorLink } from "./nodeInspector";
import { assignEdgeStepPositions } from "./graphEdges";
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

function LoadNode({
  data,
  selected,
}: {
  data: { name: string; type: string; roles?: string[]; dim?: boolean };
  selected?: boolean;
}) {
  const roles = (data.roles || []).map((role) => `role-${role}`).join(" ");
  return (
    <div className={["lp-node", selected ? "selected" : "", data.dim ? "dim" : "", roles].filter(Boolean).join(" ")}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="t">{typeLabel(data.type)}</div>
      <div className="n" title={data.name}>
        {wrapHint(data.name)}
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}

const nodeTypes = { load: LoadNode };
const ALL_FAMILIES = new Set<GraphFamily>(["django", "react", "stitch", "arch"]);

function LoadStepEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  markerStart,
  label,
  labelStyle,
  labelShowBg,
  labelBgStyle,
  labelBgPadding,
  labelBgBorderRadius,
  data,
  interactionWidth,
}: EdgeProps<Edge<{ stepPosition?: number }>>) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 8,
    stepPosition: data?.stepPosition ?? 0.5,
  });
  return (
    <BaseEdge
      id={id}
      path={path}
      labelX={labelX}
      labelY={labelY}
      label={label}
      labelStyle={labelStyle}
      labelShowBg={labelShowBg}
      labelBgStyle={labelBgStyle}
      labelBgPadding={labelBgPadding}
      labelBgBorderRadius={labelBgBorderRadius}
      style={style}
      markerEnd={markerEnd}
      markerStart={markerStart}
      interactionWidth={interactionWidth}
    />
  );
}

const edgeTypes = { loadstep: LoadStepEdge };

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
  opts: { roles?: Record<string, string[]>; testOverlay?: boolean } = {},
): { rfNodes: Node[]; rfEdges: Edge[] } {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const pos = layoutNodes(nodes, edges);
  const stepByEdge = assignEdgeStepPositions(nodes, edges, pos);
  const rfNodes: Node[] = nodes.map((n) => {
    const roles = opts.roles?.[n.id] || [];
    const dim =
      Boolean(opts.testOverlay) &&
      !roles.includes("tested") &&
      !roles.includes("untested") &&
      !roles.includes("test") &&
      !roles.includes("seed");
    return {
      id: n.id,
      type: "load",
      position: pos.get(n.id) ?? { x: 0, y: 0 },
      data: { name: n.name, type: n.type, file: n.file_path, roles, dim },
      selected: selectedId === n.id,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      width: GRAPH_NODE_WIDTH,
      height: GRAPH_NODE_HEIGHT,
      style: { width: GRAPH_NODE_WIDTH, height: GRAPH_NODE_HEIGHT },
    };
  });
  const rfEdges: Edge[] = edges
    .filter((e) => byId.has(e.src) && byId.has(e.dst))
    .map((e) => {
      const stroke = WEIGHT_COLOR[e.weight] || "var(--edge-cheap)";
      const labeled = Boolean(selectedId && (e.src === selectedId || e.dst === selectedId));
      return {
        id: e.id,
        source: e.src,
        target: e.dst,
        type: "loadstep",
        animated: e.weight === "critical",
        data: { stepPosition: stepByEdge.get(e.id) ?? 0.5 },
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
  onWhatIf,
  onSelect,
  onOpenFile,
  pinned,
  onPin,
  onIsolate,
}: {
  node: GraphNode;
  nodes: GraphNode[];
  edges: GraphEdge[];
  onClose: () => void;
  onWhatIf?: (id: string) => void;
  onSelect?: (id: string) => void;
  onOpenFile?: (path: string, line?: number | null) => void;
  pinned?: boolean;
  onPin?: (id: string | null) => void;
  onIsolate?: (id: string) => void;
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
      {info.file ? (
        <div className="file-row">
          <div className="file">{wrapHint(info.file)}</div>
          {onOpenFile && node.file_path ? (
            <button
              type="button"
              className="btn"
              data-testid="btn-open-editor"
              onClick={() => onOpenFile(node.file_path!, node.start_line)}
            >
              Open in editor
            </button>
          ) : null}
        </div>
      ) : null}
      <div className="muted">{wrapHint(info.qualifiedName)}</div>
      <div className="muted inspector-layer">layer · {info.layer}</div>
      <div className="muted inspector-degree" data-testid="graph-inspector-degree">
        {info.degreeIn} in · {info.degreeOut} out
      </div>
      {info.pathSummary ? (
        <p className="inspector-path" data-testid="graph-inspector-path">
          {info.pathSummary}
        </p>
      ) : null}
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
        onSelect={onSelect}
      />
      <InspectorLinks
        title="Outputs"
        testId="graph-inspector-outputs"
        links={info.outputs}
        extra={info.extraOutputs}
        empty="This node does not point at anything in this graph."
        onSelect={onSelect}
      />
      {onWhatIf ? (
        <p className="whatif-hint" data-testid="whatif-hint">
          {onIsolate
            ? "Walks a new path from this node with no git range. Isolate (next) only hides the rest of this map."
            : "Walks a new path from this node with no git range — as if this changed, regardless of Base/Head."}
        </p>
      ) : null}
      <div className="btn-row">
        {onWhatIf ? (
          <button
            type="button"
            className="btn"
            data-testid="btn-whatif"
            title="Start a hypothetical walk from this node. Does not use Base/Head."
            onClick={() => onWhatIf(node.id)}
          >
            What if this changes
          </button>
        ) : null}
        {onIsolate ? (
          <button
            type="button"
            className="btn"
            data-testid="btn-isolate"
            title="Hide nodes that are not on a path from here to a sink. Does not start a new walk."
            onClick={() => onIsolate(node.id)}
          >
            Isolate path to sinks
          </button>
        ) : null}
        {onPin ? (
          <button
            type="button"
            className={pinned ? "btn primary" : "btn"}
            data-testid="btn-pin-node"
            onClick={() => onPin(pinned ? null : node.id)}
          >
            {pinned ? "Unpin" : "Pin"}
          </button>
        ) : null}
      </div>
    </aside>
  );
}

function InspectorLinks({
  title,
  testId,
  links,
  extra,
  empty,
  onSelect,
}: {
  title: string;
  testId: string;
  links: InspectorLink[];
  extra: number;
  empty: string;
  onSelect?: (id: string) => void;
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
              {onSelect ? (
                <button type="button" className="inspector-link" onClick={() => onSelect(link.id)}>
                  <span className="inspector-link-name" title={link.name}>
                    {wrapHint(link.name)}
                  </span>
                  <span className="inspector-link-meta">
                    {link.typeLabel ? `${link.typeLabel} · ` : ""}
                    {link.edgeLabel}
                    {link.inferred ? " · inferred" : ""}
                  </span>
                </button>
              ) : (
                <>
                  <span className="inspector-link-name" title={link.name}>
                    {wrapHint(link.name)}
                  </span>
                  <span className="inspector-link-meta">
                    {link.typeLabel ? `${link.typeLabel} · ` : ""}
                    {link.edgeLabel}
                    {link.inferred ? " · inferred" : ""}
                  </span>
                </>
              )}
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

export function ImpactGraph({
  nodes,
  edges,
  onWhatIf,
  focusPath,
  selectedId: selectedIdProp,
  onSelect,
  nodeRoles,
  testOverlay = false,
  isolateSource,
  onIsolate,
  repoPath: _repoPath,
  onOpenFile,
  pinnedId,
  onPin,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onWhatIf?: (id: string) => void;
  focusPath?: string;
  selectedId?: string | null;
  onSelect?: (id: string | null) => void;
  nodeRoles?: Record<string, string[]>;
  testOverlay?: boolean;
  isolateSource?: string | null;
  onIsolate?: (id: string | null) => void;
  repoPath?: string;
  onOpenFile?: (path: string, line?: number | null) => void;
  pinnedId?: string | null;
  onPin?: (id: string | null) => void;
}) {
  const [localSelected, setLocalSelected] = useState<string | null>(null);
  const selectedId = selectedIdProp !== undefined ? selectedIdProp : localSelected;
  const setSelectedId = (id: string | null) => {
    if (selectedIdProp === undefined) setLocalSelected(id);
    onSelect?.(id);
  };
  const [projection, setProjection] = useState<GraphProjection | null>(null);
  const [detail, setDetail] = useState<GraphDetail | null>(null);
  const [families, setFamilies] = useState<Set<GraphFamily>>(new Set(ALL_FAMILIES));
  const [neighborhoodOnly, setNeighborhoodOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [hitsOpen, setHitsOpen] = useState(false);
  const reduceMotion =
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const view = projection ?? defaultProjection(nodes.length);
  const level = detail ?? defaultDetail(nodes.length);
  const neighborhoodFocus = neighborhoodOnly ? selectedId : null;
  const isolated = useMemo(
    () => (isolateSource ? isolatePathIds(nodes, edges, isolateSource) : null),
    [nodes, edges, isolateSource],
  );
  const scopedNodes = isolated ? nodes.filter((n) => isolated.nodeIds.has(n.id)) : nodes;
  const scopedEdges = isolated ? edges.filter((e) => isolated.edgeIds.has(e.id)) : edges;
  const visible = useMemo(
    () =>
      visibleGraph(scopedNodes, scopedEdges, {
        detail: level,
        families,
        focusId: neighborhoodFocus,
        neighborhoodOnly: Boolean(neighborhoodFocus),
      }),
    [scopedNodes, scopedEdges, level, families, neighborhoodFocus],
  );
  const topologyKey = useMemo(
    () => `${visible.nodes.map((n) => n.id).join("\0")}|${visible.edges.map((e) => e.id).join("\0")}`,
    [visible.nodes, visible.edges],
  );
  const selected = selectedId ? nodes.find((n) => n.id === selectedId) ?? null : null;
  const { rfNodes, rfEdges } = useMemo(() => {
    const elements = toReactFlowElements(visible.nodes, visible.edges, selectedId, {
      roles: nodeRoles,
      testOverlay,
    });
    if (reduceMotion) {
      elements.rfEdges = elements.rfEdges.map((edge) => ({ ...edge, animated: false }));
    }
    return elements;
  }, [visible.nodes, visible.edges, selectedId, reduceMotion, nodeRoles, testOverlay]);

  useEffect(() => {
    if (!focusPath) return;
    const match = nodes.find((n) => n.file_path === focusPath);
    if (match) setSelectedId(match.id);
  }, [focusPath, nodes]);

  const hits = useMemo(() => searchNodes(nodes, query), [nodes, query]);

  const onNodeClick: NodeMouseHandler = (_evt, node) => {
    setSelectedId(node.id);
  };

  const clearSelection = () => {
    setSelectedId(null);
    setNeighborhoodOnly(false);
  };

  const inspector = selected ? (
    <GraphInspector
      node={selected}
      nodes={nodes}
      edges={edges}
      onClose={clearSelection}
      onWhatIf={onWhatIf}
      onSelect={setSelectedId}
      onOpenFile={onOpenFile}
      pinned={pinnedId === selected.id}
      onPin={onPin}
      onIsolate={
        onIsolate
          ? (id) => {
              onIsolate(isolateSource === id ? null : id);
            }
          : undefined
      }
    />
  ) : null;

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
        <button
          type="button"
          className={neighborhoodOnly ? "chip-btn active" : "chip-btn"}
          data-testid="graph-neighborhood"
          disabled={!selectedId}
          onClick={() => setNeighborhoodOnly((v) => !v)}
        >
          {neighborhoodOnly ? "Neighborhood" : "Focus neighbors"}
        </button>
        {isolateSource ? (
          <button
            type="button"
            className="chip-btn active"
            data-testid="graph-isolate-clear"
            onClick={() => onIsolate?.(null)}
          >
            Path isolate
          </button>
        ) : null}
        <label className="graph-search">
          <span className="sr-only">Search nodes</span>
          <input
            data-testid="graph-search"
            placeholder="Find a node"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setHitsOpen(true);
            }}
            onFocus={() => setHitsOpen(true)}
            onBlur={() => window.setTimeout(() => setHitsOpen(false), 150)}
          />
          {hitsOpen && query.trim() && hits.length ? (
            <ul className="graph-search-hits" data-testid="graph-search-hits">
              {hits.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      setSelectedId(n.id);
                      setQuery("");
                      setHitsOpen(false);
                    }}
                  >
                    {n.name}
                    <span className="muted">{typeLabel(n.type)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </label>
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
            {inspector}
          </div>
        ) : (
          <ReactFlowProvider>
            <ReactFlow
              nodes={rfNodes}
              edges={rfEdges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
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
            {inspector}
          </ReactFlowProvider>
        )}
      </div>
    </div>
  );
}
