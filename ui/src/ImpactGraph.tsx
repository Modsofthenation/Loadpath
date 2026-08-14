import { Background, Controls, MiniMap, ReactFlow, ReactFlowProvider, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { layoutNodes, type GraphEdge, type GraphNode } from "./types";

const WEIGHT_COLOR: Record<string, string> = {
  cheap: "var(--edge-cheap)",
  expensive: "var(--edge-expensive)",
  critical: "var(--edge-critical)",
};

function LoadNode({ data }: { data: { name: string; type: string } }) {
  return (
    <div className="lp-node">
      <div className="t">{data.type.split(".").pop()}</div>
      <div className="n">{data.name}</div>
    </div>
  );
}

const nodeTypes = { load: LoadNode };

export function ImpactGraph({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const pos = layoutNodes(nodes);
  const rfNodes: Node[] = nodes.map((n) => ({
    id: n.id,
    type: "load",
    position: pos.get(n.id) ?? { x: 0, y: 0 },
    data: { name: n.name, type: n.type, file: n.file_path },
  }));
  const rfEdges: Edge[] = edges
    .filter((e) => nodes.some((n) => n.id === e.src) && nodes.some((n) => n.id === e.dst))
    .map((e) => ({
      id: e.id,
      source: e.src,
      target: e.dst,
      animated: e.weight === "critical",
      style: {
        stroke: WEIGHT_COLOR[e.weight] || "var(--edge-cheap)",
        strokeWidth: e.weight === "critical" ? 2.4 : 1.2,
        strokeDasharray: e.confidence < 0.8 ? "6 4" : undefined,
      },
      label: e.type.replaceAll("_", " "),
      labelStyle: { fill: "var(--muted)", fontSize: 9 },
    }));

  return (
    <ReactFlowProvider>
      <ReactFlow nodes={rfNodes} edges={rfEdges} nodeTypes={nodeTypes} fitView minZoom={0.2} data-testid="impact-graph">
        <Background />
        <MiniMap pannable zoomable />
        <Controls />
      </ReactFlow>
    </ReactFlowProvider>
  );
}
