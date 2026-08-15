import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { typeLabel } from "./format";
import { layoutNodes, type GraphEdge, type GraphNode } from "./types";

const WEIGHT_COLOR: Record<string, string> = {
  cheap: "var(--edge-cheap)",
  expensive: "var(--edge-expensive)",
  critical: "var(--edge-critical)",
};

function LoadNode({ data, selected }: { data: { name: string; type: string }; selected?: boolean }) {
  return (
    <div className={selected ? "lp-node selected" : "lp-node"}>
      <div className="t">{typeLabel(data.type)}</div>
      <div className="n">{data.name}</div>
    </div>
  );
}

const nodeTypes = { load: LoadNode };

export function ImpactGraph({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const reduceMotion =
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pos = layoutNodes(nodes);
  const rfNodes: Node[] = nodes.map((n) => ({
    id: n.id,
    type: "load",
    position: pos.get(n.id) ?? { x: 0, y: 0 },
    data: { name: n.name, type: n.type, file: n.file_path },
    selected: selected?.id === n.id,
  }));
  const rfEdges: Edge[] = edges
    .filter((e) => nodes.some((n) => n.id === e.src) && nodes.some((n) => n.id === e.dst))
    .map((e) => ({
      id: e.id,
      source: e.src,
      target: e.dst,
      animated: !reduceMotion && e.weight === "critical",
      style: {
        stroke: WEIGHT_COLOR[e.weight] || "var(--edge-cheap)",
        strokeWidth: e.weight === "critical" ? 2.4 : 1.2,
        strokeDasharray: e.confidence < 0.8 ? "6 4" : undefined,
      },
      label: e.type.replaceAll("_", " "),
      labelStyle: { fill: "var(--muted)", fontSize: 10 },
    }));

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const onNodeClick: NodeMouseHandler = (_evt, node) => {
    setSelected(byId.get(node.id) ?? null);
  };

  return (
    <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
      <ReactFlowProvider>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2, maxZoom: 1.15 }}
          minZoom={0.25}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          deleteKeyCode={null}
          onNodeClick={onNodeClick}
          onPaneClick={() => setSelected(null)}
          proOptions={{ hideAttribution: false }}
          data-testid="impact-graph"
        >
          <Background />
          <MiniMap pannable zoomable />
          <Controls />
        </ReactFlow>
      </ReactFlowProvider>
      {selected ? (
        <aside className="inspector" data-testid="graph-inspector">
          <div className="t">{typeLabel(selected.type)}</div>
          <div className="n">{selected.name}</div>
          {selected.context ? <div className="muted">{selected.context}</div> : null}
          {selected.file_path ? (
            <div className="file">
              {selected.file_path}
              {selected.start_line ? `:${selected.start_line}` : ""}
            </div>
          ) : null}
          <div className="muted">{selected.qualified_name}</div>
        </aside>
      ) : null}
    </div>
  );
}
