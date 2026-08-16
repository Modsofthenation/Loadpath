import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { typeLabel } from "./format";
import {
  colorForType,
  isInferredEdge,
  layoutGuides3d,
  layoutNodes3d,
  nodeRadius3d,
  type GraphLayoutId,
} from "./graphView";
import type { GraphEdge, GraphNode } from "./types";

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  neighborIds: Set<string>;
  onSelect: (id: string | null) => void;
  layout?: GraphLayoutId;
  nodeRoles?: Record<string, string[]>;
  testOverlay?: boolean;
};

type HostEl = HTMLDivElement & {
  __paint?: (id: string | null, neighbors: Set<string>) => void;
  __focus?: (id: string | null) => void;
};

const LABEL_LIMIT = 64;
const ARROW_LIMIT = 150;

function cssColor(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function truncateLabel(text: string, max = 26): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

function makeTextSprite(text: string, color: string, opts: { width: number; height: number; font: string }): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = opts.width;
  canvas.height = opts.height;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.clearRect(0, 0, opts.width, opts.height);
    ctx.fillStyle = color;
    ctx.font = opts.font;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, opts.width / 2, opts.height / 2);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  sprite.scale.set(opts.width * 0.22, opts.height * 0.22, 1);
  return sprite;
}

function makeLayerLabel(text: string, color: string): THREE.Sprite {
  const sprite = makeTextSprite(text, color, { width: 512, height: 64, font: "600 28px sans-serif" });
  sprite.scale.set(110, 14, 1);
  return sprite;
}

function makeNodeLabel(text: string, color: string): THREE.Sprite {
  const sprite = makeTextSprite(truncateLabel(text), color, { width: 384, height: 48, font: "600 22px sans-serif" });
  sprite.scale.set(52, 6.5, 1);
  return sprite;
}

function edgeBaseColor(
  edge: GraphEdge,
  cheap: THREE.Color,
  expensive: THREE.Color,
  critical: THREE.Color,
): THREE.Color {
  if (edge.weight === "critical") return critical;
  if (edge.weight === "expensive") return expensive;
  return cheap;
}

export function LayeredGraph3D({
  nodes,
  edges,
  selectedId,
  neighborIds,
  onSelect,
  layout = "layers",
  nodeRoles,
  testOverlay = false,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ node: GraphNode; x: number; y: number } | null>(null);
  const [webglError, setWebglError] = useState<string | null>(null);
  const [theme, setTheme] = useState(
    () => (typeof document === "undefined" ? "obsidian" : document.documentElement.dataset.theme || "obsidian"),
  );
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const focusRef = useRef({ selectedId, neighborIds });
  focusRef.current = { selectedId, neighborIds };
  const rolesRef = useRef({ nodeRoles, testOverlay });
  rolesRef.current = { nodeRoles, testOverlay };
  const cameraStateRef = useRef<{
    position: { x: number; y: number; z: number };
    target: { x: number; y: number; z: number };
    topology: string;
  } | null>(null);
  const didFocusRef = useRef(false);
  const topologyKey = `${layout}|${nodes.map((n) => n.id).join("\0")}|${edges.map((e) => e.id).join("\0")}`;

  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setTheme(root.dataset.theme || "obsidian");
    const obs = new MutationObserver(sync);
    obs.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const bg = cssColor("--graph-bg", "#0b0f14");
    const ink = cssColor("--ink", "#e8eef7");
    const accent = new THREE.Color(cssColor("--accent", "#4cc9f0"));
    const low = new THREE.Color(cssColor("--low", "#e76f51"));
    const high = new THREE.Color(cssColor("--high", "#2a9d8f"));
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(bg);
    scene.fog = new THREE.Fog(new THREE.Color(bg), 520, 2800);

    const camera = new THREE.PerspectiveCamera(50, 1, 1, 8000);
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: false,
        failIfMajorPerformanceCaveat: false,
        powerPreference: "low-power",
      });
    } catch {
      setWebglError("WebGL is unavailable in this browser, so the 3D view cannot start. Switch back to 2D map.");
      return;
    }
    if (!renderer.getContext()) {
      renderer.dispose();
      setWebglError("WebGL is unavailable in this browser, so the 3D view cannot start. Switch back to 2D map.");
      return;
    }
    setWebglError(null);
    renderer.setClearColor(bg, 1);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.domElement.dataset.testid = "graph-3d-canvas";
    host.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = !reduceMotion;
    controls.dampingFactor = 0.08;
    controls.minDistance = 80;
    controls.maxDistance = 2400;

    scene.add(new THREE.HemisphereLight(0xffffff, 0x1a2433, 0.55));
    scene.add(new THREE.AmbientLight(0xffffff, 0.42));
    const key = new THREE.DirectionalLight(0xffffff, 0.8);
    key.position.set(200, 320, 180);
    scene.add(key);

    const pos = layoutNodes3d(nodes, edges, layout);
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const meshById = new Map<string, THREE.Mesh>();
    const labelById = new Map<string, THREE.Sprite>();
    const group = new THREE.Group();
    scene.add(group);

    const sphere = new THREE.SphereGeometry(1, 18, 14);
    const showLabels = nodes.length <= LABEL_LIMIT;
    const labelSprites: THREE.Sprite[] = [];
    for (const node of nodes) {
      const p = pos.get(node.id) ?? { x: 0, y: 0, z: 0 };
      const radius = nodeRadius3d(node.type);
      const material = new THREE.MeshStandardMaterial({
        color: colorForType(node.type),
        roughness: 0.42,
        metalness: 0.08,
        transparent: true,
        opacity: 1,
      });
      const mesh = new THREE.Mesh(sphere, material);
      mesh.position.set(p.x, p.y, p.z);
      mesh.scale.setScalar(radius);
      mesh.userData.id = node.id;
      group.add(mesh);
      meshById.set(node.id, mesh);
      if (showLabels) {
        const label = makeNodeLabel(node.name, ink);
        label.position.set(p.x, p.y + radius + 8, p.z);
        group.add(label);
        labelById.set(node.id, label);
        labelSprites.push(label);
      }
    }

    const cheap = new THREE.Color(cssColor("--edge-cheap", "#4a5568"));
    const expensive = new THREE.Color(cssColor("--edge-expensive", "#f4a261"));
    const critical = new THREE.Color(cssColor("--edge-critical", "#e85d04"));
    type EdgeDraw = {
      edge: GraphEdge;
      a: { x: number; y: number; z: number };
      b: { x: number; y: number; z: number };
      color: THREE.Color;
      inferred: boolean;
      solidIndex: number;
      dashedIndex: number;
    };
    const drawn: EdgeDraw[] = [];
    const solidPos: number[] = [];
    const solidCol: number[] = [];
    const dashPos: number[] = [];
    const dashCol: number[] = [];
    for (const edge of edges) {
      const a = pos.get(edge.src);
      const b = pos.get(edge.dst);
      if (!a || !b) continue;
      const color = edgeBaseColor(edge, cheap, expensive, critical);
      const inferred = isInferredEdge(edge);
      const src = color.clone().multiplyScalar(0.55);
      if (inferred) {
        drawn.push({
          edge,
          a,
          b,
          color,
          inferred,
          solidIndex: -1,
          dashedIndex: dashPos.length / 3,
        });
        dashPos.push(a.x, a.y, a.z, b.x, b.y, b.z);
        dashCol.push(src.r, src.g, src.b, color.r, color.g, color.b);
      } else {
        drawn.push({
          edge,
          a,
          b,
          color,
          inferred,
          solidIndex: solidPos.length / 3,
          dashedIndex: -1,
        });
        solidPos.push(a.x, a.y, a.z, b.x, b.y, b.z);
        solidCol.push(src.r, src.g, src.b, color.r, color.g, color.b);
      }
    }

    const solidGeom = new THREE.BufferGeometry();
    solidGeom.setAttribute("position", new THREE.Float32BufferAttribute(solidPos, 3));
    solidGeom.setAttribute("color", new THREE.Float32BufferAttribute(solidCol, 3));
    const solidLines = new THREE.LineSegments(
      solidGeom,
      new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.58 }),
    );
    group.add(solidLines);

    const dashGeom = new THREE.BufferGeometry();
    dashGeom.setAttribute("position", new THREE.Float32BufferAttribute(dashPos, 3));
    dashGeom.setAttribute("color", new THREE.Float32BufferAttribute(dashCol, 3));
    const dashMat = new THREE.LineDashedMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.5,
      dashSize: 7,
      gapSize: 5,
    });
    const dashLines = new THREE.LineSegments(dashGeom, dashMat);
    dashLines.computeLineDistances();
    group.add(dashLines);

    const arrowGeom = new THREE.ConeGeometry(2.2, 7, 8);
    const arrows: THREE.Mesh[] = [];
    const showArrows = drawn.length <= ARROW_LIMIT;
    if (showArrows) {
      const up = new THREE.Vector3(0, 1, 0);
      const dir = new THREE.Vector3();
      for (const item of drawn) {
        const material = new THREE.MeshBasicMaterial({
          color: item.color,
          transparent: true,
          opacity: 0.85,
        });
        const arrow = new THREE.Mesh(arrowGeom, material);
        dir.set(item.b.x - item.a.x, item.b.y - item.a.y, item.b.z - item.a.z);
        const len = dir.length();
        if (len < 8) {
          arrow.visible = false;
        } else {
          dir.multiplyScalar(1 / len);
          const destR = nodeRadius3d(byId.get(item.edge.dst)?.type || "");
          const hold = Math.min(len - 4, destR + 5);
          arrow.position.set(
            item.b.x - dir.x * hold,
            item.b.y - dir.y * hold,
            item.b.z - dir.z * hold,
          );
          arrow.quaternion.setFromUnitVectors(up, dir);
        }
        arrow.userData.src = item.edge.src;
        arrow.userData.dst = item.edge.dst;
        group.add(arrow);
        arrows.push(arrow);
      }
    }

    const planeMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(cssColor("--node-line", "#2a3d52")),
      transparent: true,
      opacity: 0.16,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const lineMat = new THREE.LineBasicMaterial({
      color: new THREE.Color(cssColor("--muted", "#8b9bb0")),
      transparent: true,
      opacity: 0.28,
    });
    const labelColor = cssColor("--muted", "#8b9bb0");
    const layerLabels: THREE.Sprite[] = [];
    const guideGeoms: THREE.BufferGeometry[] = [];
    const planeGeom = new THREE.PlaneGeometry(1, 1);
    guideGeoms.push(planeGeom);
    for (const guide of layoutGuides3d(nodes, pos, layout)) {
      if (guide.shape === "slab") {
        const slab = new THREE.Mesh(planeGeom, planeMat);
        slab.scale.set(guide.extentZ * 2, guide.extentY * 2, 1);
        slab.rotation.y = Math.PI / 2;
        slab.position.set(guide.x, guide.y, guide.z);
        group.add(slab);
        const outline = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(guide.x, guide.y - guide.extentY, guide.z - guide.extentZ),
          new THREE.Vector3(guide.x, guide.y + guide.extentY, guide.z - guide.extentZ),
          new THREE.Vector3(guide.x, guide.y + guide.extentY, guide.z + guide.extentZ),
          new THREE.Vector3(guide.x, guide.y - guide.extentY, guide.z + guide.extentZ),
        ]);
        guideGeoms.push(outline);
        group.add(new THREE.LineLoop(outline, lineMat));
        if (guide.label) {
          const label = makeLayerLabel(guide.label, labelColor);
          label.position.set(guide.x, guide.y + guide.extentY + 12, guide.z);
          group.add(label);
          layerLabels.push(label);
        }
      } else if (guide.radius >= 12) {
        const ringPts: THREE.Vector3[] = [];
        for (let i = 0; i < 64; i += 1) {
          const theta = (i / 64) * Math.PI * 2;
          ringPts.push(
            new THREE.Vector3(Math.cos(theta) * guide.radius, Math.sin(theta) * guide.radius, guide.z),
          );
        }
        const ringGeom = new THREE.BufferGeometry().setFromPoints(ringPts);
        guideGeoms.push(ringGeom);
        group.add(new THREE.LineLoop(ringGeom, lineMat));
      }
    }

    const saved = cameraStateRef.current;
    if (saved && saved.topology === topologyKey) {
      camera.position.set(saved.position.x, saved.position.y, saved.position.z);
      controls.target.set(saved.target.x, saved.target.y, saved.target.z);
      camera.lookAt(controls.target);
    } else {
      const box = new THREE.Box3().setFromObject(group);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      controls.target.copy(center);
      camera.position.set(
        center.x + size.x * 0.15,
        center.y + Math.max(140, size.y * 0.45),
        center.z + Math.max(280, size.z * 0.9 + 180),
      );
      camera.lookAt(center);
    }

    const raycaster = new THREE.Raycaster();
    raycaster.params.Mesh = { ...raycaster.params.Mesh, threshold: 2 };
    const pointer = new THREE.Vector2();
    const meshes = [...meshById.values()];
    let goalTarget: THREE.Vector3 | null = null;
    let goalCamera: THREE.Vector3 | null = null;

    const writeEdgeColor = (item: EdgeDraw, mul: number) => {
      const src = item.color.clone().multiplyScalar(0.55 * mul);
      const dst = item.color.clone().multiplyScalar(mul);
      const colors = item.inferred
        ? (dashGeom.getAttribute("color") as THREE.BufferAttribute)
        : (solidGeom.getAttribute("color") as THREE.BufferAttribute);
      const index = item.inferred ? item.dashedIndex : item.solidIndex;
      if (index < 0) return;
      colors.setXYZ(index, src.r, src.g, src.b);
      colors.setXYZ(index + 1, dst.r, dst.g, dst.b);
    };

    const paint = (focus: string | null, neighbors: Set<string>) => {
      const isolating = Boolean(focus && neighbors.size);
      const roles = rolesRef.current.nodeRoles || {};
      const overlay = rolesRef.current.testOverlay;
      for (const [id, mesh] of meshById) {
        const node = byId.get(id);
        const material = mesh.material as THREE.MeshStandardMaterial;
        const onPath = !isolating || neighbors.has(id);
        const selected = id === focus;
        const nodeRolesFor = roles[id] || [];
        const radius = nodeRadius3d(node?.type || "");
        let scale = radius;
        if (selected) scale *= 1.28;
        else if (!onPath) scale *= 0.7;
        else if (nodeRolesFor.includes("seed")) scale *= 1.12;
        mesh.scale.setScalar(scale);
        material.opacity = selected ? 1 : onPath ? 0.96 : 0.12;
        if (selected) {
          material.emissive.copy(accent);
          material.emissiveIntensity = 0.4;
        } else if (nodeRolesFor.includes("untested")) {
          material.emissive.copy(low);
          material.emissiveIntensity = onPath ? 0.32 : 0.05;
        } else if (overlay && nodeRolesFor.includes("tested")) {
          material.emissive.copy(high);
          material.emissiveIntensity = onPath ? 0.22 : 0.04;
        } else if (nodeRolesFor.includes("seed")) {
          material.emissive.copy(accent);
          material.emissiveIntensity = onPath ? 0.2 : 0.04;
        } else if (nodeRolesFor.includes("contract")) {
          material.emissive.copy(accent);
          material.emissiveIntensity = onPath ? 0.16 : 0.03;
        } else {
          material.emissive.set(0x000000);
          material.emissiveIntensity = 0;
        }
        const p = pos.get(id) ?? { x: 0, y: 0, z: 0 };
        const label = labelById.get(id);
        if (label) {
          label.visible = selected || (isolating && neighbors.has(id)) || (!focus && showLabels);
          label.position.set(p.x, p.y + scale + 8, p.z);
        }
      }
      (solidLines.material as THREE.LineBasicMaterial).opacity = isolating ? 0.9 : 0.55;
      dashMat.opacity = isolating ? 0.78 : 0.48;
      for (const item of drawn) {
        const incident = Boolean(focus && (item.edge.src === focus || item.edge.dst === focus));
        const onPath =
          !isolating || (neighbors.has(item.edge.src) && neighbors.has(item.edge.dst));
        const mul = incident ? 1 : onPath ? 0.85 : 0.12;
        writeEdgeColor(item, mul);
      }
      if (drawn.length) {
        (solidGeom.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
        (dashGeom.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
      }
      for (const arrow of arrows) {
        const src = arrow.userData.src as string;
        const dst = arrow.userData.dst as string;
        const incident = Boolean(focus && (src === focus || dst === focus));
        const onPath = !isolating || (neighbors.has(src) && neighbors.has(dst));
        arrow.visible = onPath && (drawn.length <= 80 || incident);
        (arrow.material as THREE.MeshBasicMaterial).opacity = incident ? 1 : 0.75;
      }
    };

    const focusNode = (id: string | null) => {
      if (!id) {
        goalTarget = null;
        goalCamera = null;
        return;
      }
      const p = pos.get(id);
      if (!p) return;
      const dest = new THREE.Vector3(p.x, p.y, p.z);
      const offset = camera.position.clone().sub(controls.target);
      if (offset.length() < 40) offset.set(90, 110, 180);
      if (reduceMotion) {
        controls.target.copy(dest);
        camera.position.copy(dest).add(offset);
        goalTarget = null;
        goalCamera = null;
        return;
      }
      goalTarget = dest;
      goalCamera = dest.clone().add(offset);
    };

    const setPointer = (event: { clientX: number; clientY: number }) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    };
    const hit = (): GraphNode | null => {
      raycaster.setFromCamera(pointer, camera);
      const found = raycaster.intersectObjects(meshes, false)[0];
      const id = found?.object.userData.id as string | undefined;
      return id ? byId.get(id) ?? null : null;
    };

    const onMove = (event: PointerEvent) => {
      setPointer(event);
      const node = hit();
      if (!node) {
        setHover(null);
        renderer.domElement.style.cursor = "grab";
        return;
      }
      renderer.domElement.style.cursor = "pointer";
      const rect = (wrapRef.current ?? host).getBoundingClientRect();
      setHover({ node, x: event.clientX - rect.left, y: event.clientY - rect.top });
    };
    const onClick = (event: MouseEvent) => {
      setPointer(event);
      const node = hit();
      selectRef.current(node ? node.id : null);
    };
    const onControlStart = () => {
      goalTarget = null;
      goalCamera = null;
    };

    const resize = () => {
      const w = host.clientWidth || 1;
      const h = host.clientHeight || 1;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);

    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      if (goalTarget && goalCamera) {
        controls.target.lerp(goalTarget, 0.14);
        camera.position.lerp(goalCamera, 0.14);
        if (controls.target.distanceTo(goalTarget) < 1.5) {
          controls.target.copy(goalTarget);
          camera.position.copy(goalCamera);
          goalTarget = null;
          goalCamera = null;
        }
      }
      controls.update();
      renderer.render(scene, camera);
    };
    tick();

    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("click", onClick);
    controls.addEventListener("start", onControlStart);
    (host as HostEl).__paint = paint;
    (host as HostEl).__focus = focusNode;
    paint(focusRef.current.selectedId, focusRef.current.neighborIds);

    return () => {
      cameraStateRef.current = {
        topology: topologyKey,
        position: { x: camera.position.x, y: camera.position.y, z: camera.position.z },
        target: { x: controls.target.x, y: controls.target.y, z: controls.target.z },
      };
      cancelAnimationFrame(frame);
      ro.disconnect();
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("click", onClick);
      controls.removeEventListener("start", onControlStart);
      delete (host as HostEl).__paint;
      delete (host as HostEl).__focus;
      controls.dispose();
      sphere.dispose();
      arrowGeom.dispose();
      solidGeom.dispose();
      dashGeom.dispose();
      planeMat.dispose();
      lineMat.dispose();
      for (const geom of guideGeoms) geom.dispose();
      (solidLines.material as THREE.Material).dispose();
      dashMat.dispose();
      for (const sprite of [...layerLabels, ...labelSprites]) {
        const material = sprite.material as THREE.SpriteMaterial;
        material.map?.dispose();
        material.dispose();
      }
      for (const mesh of meshById.values()) {
        (mesh.material as THREE.Material).dispose();
      }
      for (const arrow of arrows) {
        (arrow.material as THREE.Material).dispose();
      }
      renderer.dispose();
      renderer.domElement.remove();
      setHover(null);
    };
    // Rebuild when the graph, layout, or theme changes — not when selection paints.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topologyKey, theme]);

  useEffect(() => {
    (hostRef.current as HostEl | null)?.__paint?.(selectedId, neighborIds);
  }, [selectedId, neighborIds, nodeRoles, testOverlay]);

  useEffect(() => {
    if (!didFocusRef.current) {
      didFocusRef.current = true;
      return;
    }
    (hostRef.current as HostEl | null)?.__focus?.(selectedId);
  }, [selectedId]);

  return (
    <div className="graph-3d-host" ref={wrapRef}>
      <div className="graph-3d-canvas-host" ref={hostRef} />
      {webglError ? (
        <p className="muted graph-3d-hint" data-testid="graph-3d-fallback">
          {webglError}
        </p>
      ) : null}
      {hover ? (
        <div className="graph-3d-tip" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          <div className="t">
            {typeLabel(hover.node.type)}
            {hover.node.context ? ` · ${hover.node.context}` : ""}
          </div>
          <div className="n">{hover.node.name}</div>
          {hover.node.file_path ? <div className="f">{hover.node.file_path}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
