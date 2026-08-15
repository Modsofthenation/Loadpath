import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { typeLabel } from "./format";
import { colorForType, LAYER_LABELS, layoutNodes3d, layerCenters } from "./graphView";
import type { GraphEdge, GraphNode } from "./types";

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  neighborIds: Set<string>;
  onSelect: (id: string | null) => void;
};

type HostEl = HTMLDivElement & {
  __paint?: (id: string | null, neighbors: Set<string>) => void;
};

function cssColor(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function discRadius(count: number): number {
  return Math.max(40, 26 * Math.sqrt(Math.max(count, 1)));
}

function makeLayerLabel(text: string, color: string): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.clearRect(0, 0, 512, 64);
    ctx.fillStyle = color;
    ctx.font = "600 28px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 256, 32);
  }
  const tex = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  sprite.scale.set(110, 14, 1);
  return sprite;
}

export function LayeredGraph3D({ nodes, edges, selectedId, neighborIds, onSelect }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ node: GraphNode; x: number; y: number } | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const focusRef = useRef({ selectedId, neighborIds });
  focusRef.current = { selectedId, neighborIds };

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(cssColor("--graph-bg", "#0b0f14"));

    const camera = new THREE.PerspectiveCamera(50, 1, 1, 8000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.domElement.dataset.testid = "graph-3d-canvas";
    host.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = !reduceMotion;
    controls.dampingFactor = 0.08;
    controls.minDistance = 80;
    controls.maxDistance = 2400;

    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const key = new THREE.DirectionalLight(0xffffff, 0.85);
    key.position.set(200, 320, 180);
    scene.add(key);

    const pos = layoutNodes3d(nodes);
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const meshById = new Map<string, THREE.Mesh>();
    const group = new THREE.Group();
    scene.add(group);

    const sphere = new THREE.SphereGeometry(8, 18, 14);
    for (const node of nodes) {
      const p = pos.get(node.id) ?? { x: 0, y: 0, z: 0 };
      const material = new THREE.MeshStandardMaterial({
        color: colorForType(node.type),
        roughness: 0.45,
        metalness: 0.05,
        transparent: true,
        opacity: 1,
      });
      const mesh = new THREE.Mesh(sphere, material);
      mesh.position.set(p.x, p.y, p.z);
      mesh.userData.id = node.id;
      group.add(mesh);
      meshById.set(node.id, mesh);
    }

    const edgeGeom = new THREE.BufferGeometry();
    const edgePositions: number[] = [];
    const edgeColors: number[] = [];
    const cheap = new THREE.Color(cssColor("--edge-cheap", "#4a5568"));
    const expensive = new THREE.Color(cssColor("--edge-expensive", "#f4a261"));
    const critical = new THREE.Color(cssColor("--edge-critical", "#e85d04"));
    for (const edge of edges) {
      const a = pos.get(edge.src);
      const b = pos.get(edge.dst);
      if (!a || !b) continue;
      edgePositions.push(a.x, a.y, a.z, b.x, b.y, b.z);
      const color = edge.weight === "critical" ? critical : edge.weight === "expensive" ? expensive : cheap;
      edgeColors.push(color.r, color.g, color.b, color.r, color.g, color.b);
    }
    edgeGeom.setAttribute("position", new THREE.Float32BufferAttribute(edgePositions, 3));
    edgeGeom.setAttribute("color", new THREE.Float32BufferAttribute(edgeColors, 3));
    const lines = new THREE.LineSegments(
      edgeGeom,
      new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55 }),
    );
    group.add(lines);

    const planeMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(cssColor("--muted", "#8b9bb0")),
      transparent: true,
      opacity: 0.07,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const labelColor = cssColor("--muted", "#8b9bb0");
    const labels: THREE.Sprite[] = [];
    for (const layer of layerCenters(nodes)) {
      const disc = new THREE.Mesh(new THREE.CircleGeometry(discRadius(layer.count), 48), planeMat);
      disc.rotation.y = Math.PI / 2;
      disc.position.x = layer.x;
      group.add(disc);
      const label = makeLayerLabel(LAYER_LABELS[layer.layer] ?? `layer ${layer.layer}`, labelColor);
      label.position.set(layer.x, discRadius(layer.count) + 18, 0);
      group.add(label);
      labels.push(label);
    }

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

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const meshes = [...meshById.values()];
    let drag = { x: 0, y: 0, moved: false };

    const paint = (focus: string | null, neighbors: Set<string>) => {
      const isolating = Boolean(focus && neighbors.size);
      for (const [id, mesh] of meshById) {
        const material = mesh.material as THREE.MeshStandardMaterial;
        const onPath = !isolating || neighbors.has(id);
        const selected = id === focus;
        material.opacity = selected ? 1 : onPath ? 0.95 : 0.12;
        mesh.scale.setScalar(selected ? 1.7 : onPath ? 1 : 0.7);
        material.emissive.setHex(selected ? 0xffffff : 0x000000);
        material.emissiveIntensity = selected ? 0.18 : 0;
      }
      (lines.material as THREE.LineBasicMaterial).opacity = isolating ? 0.85 : 0.5;
    };

    const setPointer = (event: PointerEvent) => {
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
      if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 4) drag.moved = true;
      setPointer(event);
      const node = hit();
      if (!node) {
        setHover(null);
        renderer.domElement.style.cursor = "grab";
        return;
      }
      renderer.domElement.style.cursor = "pointer";
      const rect = host.getBoundingClientRect();
      setHover({ node, x: event.clientX - rect.left, y: event.clientY - rect.top });
    };
    const onDown = (event: PointerEvent) => {
      drag = { x: event.clientX, y: event.clientY, moved: false };
    };
    const onUp = (event: PointerEvent) => {
      if (drag.moved) return;
      setPointer(event);
      const node = hit();
      selectRef.current(node ? node.id : null);
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
      controls.update();
      renderer.render(scene, camera);
    };
    tick();

    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    (host as HostEl).__paint = paint;
    paint(focusRef.current.selectedId, focusRef.current.neighborIds);

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      delete (host as HostEl).__paint;
      controls.dispose();
      sphere.dispose();
      edgeGeom.dispose();
      planeMat.dispose();
      (lines.material as THREE.Material).dispose();
      for (const label of labels) {
        const material = label.material as THREE.SpriteMaterial;
        material.map?.dispose();
        material.dispose();
      }
      for (const mesh of meshById.values()) {
        (mesh.material as THREE.Material).dispose();
      }
      renderer.dispose();
      renderer.domElement.remove();
      setHover(null);
    };
  }, [nodes, edges]);

  useEffect(() => {
    (hostRef.current as HostEl | null)?.__paint?.(selectedId, neighborIds);
  }, [selectedId, neighborIds]);

  return (
    <div className="graph-3d-host" ref={hostRef}>
      {hover ? (
        <div className="graph-3d-tip" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          <div className="t">{typeLabel(hover.node.type)}</div>
          <div className="n">{hover.node.name}</div>
        </div>
      ) : null}
    </div>
  );
}
