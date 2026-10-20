/**
 * Version-bound adapter for Three.js 0.186.1.
 * The convenience WebGPURenderer installs a WebGL fallback. Construct the
 * common renderer with the WebGPU backend instead; getFallback stays null.
 */
import Renderer from "three/src/renderers/common/Renderer.js";
import WebGPUBackend from "three/src/renderers/webgpu/WebGPUBackend.js";
import StandardNodeLibrary from "three/src/renderers/webgpu/nodes/StandardNodeLibrary.js";
import {
  AmbientLight, Color, DirectionalLight, Group, InstancedMesh, LineBasicMaterial,
  LineSegments, Matrix4, MeshStandardMaterial, OctahedronGeometry, OrthographicCamera,
  Raycaster, Scene, SphereGeometry, TorusGeometry, BoxGeometry, BufferGeometry,
  Float32BufferAttribute, Vector2, Vector3,
} from "three/src/Three.Core.js";
import type { TimelineDisplayCluster } from "./timeline-display";
import { FAMILY_COLORS } from "./families";

export type AxisLabel = { x: number; y: number; text: string; axis: "x" | "y" };
export type TimelineSceneInput = {
  width: number; height: number; clusters: TimelineDisplayCluster[];
  xRange: [number, number]; yRange: [number, number]; logarithmic: boolean;
};
export type TimelineScene = {
  perspective: (enabled: boolean) => void;
  zoom: (factor: number) => void;
  pick: (x: number, y: number) => TimelineDisplayCluster | null;
  rotate: (dx: number, dy: number) => void;
  pan: (dx: number, dy: number) => void;
  dispose: () => void;
};

export function chartPosition(cluster: Pick<TimelineDisplayCluster, "year" | "tc_kelvin">, input: TimelineSceneInput) {
  const [x0, x1] = input.xRange, [y0, y1] = input.yRange;
  const value = input.logarithmic ? Math.log10(cluster.tc_kelvin) : cluster.tc_kelvin;
  if (!Number.isFinite(value) || value < y0 || value > y1 || cluster.year < x0 || cluster.year > x1) return null;
  return {
    x: 70 + (cluster.year - x0) / Math.max(1, x1 - x0) * (input.width - 100),
    y: input.height - 70 - (value - y0) / Math.max(0.000001, y1 - y0) * (input.height - 110),
  };
}

export async function createTimelineScene(
  canvas: HTMLCanvasElement, input: TimelineSceneInput,
  onLabels: (labels: AxisLabel[]) => void, onLost: () => void,
): Promise<TimelineScene> {
  if (!("gpu" in navigator) || !navigator.gpu) throw new Error("WebGPU unavailable");
  const backend = new WebGPUBackend({ canvas });
  const gpuBackend = backend as WebGPUBackend & { device?: { destroy: () => void; lost: Promise<unknown> } };
  const renderer = new Renderer(backend, { getFallback: null, antialias: true });
  let disposed = false;
  renderer.library = new StandardNodeLibrary();
  renderer.onDeviceLost = onLost;
  renderer.onError = onLost;
  try { await renderer.init(); } catch (error) {
    // Renderer.dispose() re-enters init through setAnimationLoop in this pinned
    // Three.js version. A failed init has no renderer managers to dispose.
    gpuBackend.device?.destroy();
    throw error;
  }
  // Also cover external destruction. Three.js ignores the "destroyed" reason.
  void gpuBackend.device?.lost.then(() => { if (!disposed) onLost(); });
  const { width, height } = input;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setSize(width, height, false);
  renderer.setClearColor("#fbfcf8", 1);
  const scene = new Scene();
  const group = new Group();
  scene.add(group, new AmbientLight(0xffffff, 2));
  const light = new DirectionalLight(0xffffff, 3);
  light.position.set(-150, 250, 400); scene.add(light);
  const camera = new OrthographicCamera(-width / 2, width / 2, height / 2, -height / 2, 1, 2000);
  camera.position.z = 1000;
  const batches: { mesh: InstancedMesh; clusters: TimelineDisplayCluster[] }[] = [];
  const resources: { dispose: () => void }[] = [];
  const world = (x: number, y: number, z = 0) => new Vector3(x - width / 2, height / 2 - y, z);
  const groups = new Map<string, TimelineDisplayCluster[]>();
  for (const cluster of input.clusters) {
    if (!chartPosition(cluster, input)) continue;
    const members = groups.get(cluster.origin) ?? []; members.push(cluster); groups.set(cluster.origin, members);
  }
  for (const [origin, clusters] of groups) {
    const geometry = origin === "Observed" ? new SphereGeometry(5.3, 16, 12) :
      origin === "Computed" ? new TorusGeometry(5, 1.3, 8, 20) :
      origin === "Unknown / conflict" ? (() => {
        const first = new BoxGeometry(12, 2, 2), second = new BoxGeometry(2, 12, 2);
        const a = first.toNonIndexed(), b = second.toNonIndexed();
        first.dispose(); second.dispose();
        a.rotateZ(Math.PI / 4); b.rotateZ(Math.PI / 4);
        const merged = new BufferGeometry();
        for (const name of ["position", "normal"]) {
          const left = a.getAttribute(name), right = b.getAttribute(name);
          const values = new Float32Array(left.array.length + right.array.length);
          values.set(left.array); values.set(right.array, left.array.length);
          merged.setAttribute(name, new Float32BufferAttribute(values, left.itemSize));
        }
        a.dispose(); b.dispose(); return merged;
      })() :
      origin === "Mixed origins" ? new BoxGeometry(9, 9, 3) : new OctahedronGeometry(6);
    const material = new MeshStandardMaterial({ roughness: .36, metalness: .08, wireframe: origin === "Mixed origins" });
    const mesh = new InstancedMesh(geometry, material, clusters.length);
    const transform = new Matrix4();
    clusters.forEach((cluster, index) => {
      const position = chartPosition(cluster, input)!;
      const size = Math.min(1.8, 1 + Math.log2(cluster.members.length) * .15);
      transform.makeScale(size, size, size).setPosition(world(position.x, position.y));
      mesh.setMatrixAt(index, transform);
      mesh.setColorAt(index, new Color(FAMILY_COLORS[cluster.family] ?? "#536b60"));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
    group.add(mesh); batches.push({ mesh, clusters }); resources.push(geometry, material);
  }
  const tickAnchors: { point: Vector3; text: string; axis: "x" | "y" }[] = [];
  const linePoints: number[] = [];
  const line = (x0: number, y0: number, x1: number, y1: number) => {
    linePoints.push(...world(x0, y0, -10).toArray(), ...world(x1, y1, -10).toArray());
  };
  for (let i = 0; i <= 5; i++) {
    const t = i / 5;
    const x = 70 + t * (width - 100), y = height - 70 - t * (height - 110);
    line(x, 40, x, height - 70); line(70, y, width - 30, y);
    const year = input.xRange[0] + t * (input.xRange[1] - input.xRange[0]);
    const value = input.yRange[0] + t * (input.yRange[1] - input.yRange[0]);
    tickAnchors.push({ point: world(x, height - 48), text: String(Math.round(year)), axis: "x" },
      { point: world(54, y), text: new Intl.NumberFormat("en-US", { maximumSignificantDigits: 3 }).format(input.logarithmic ? 10 ** value : value), axis: "y" });
  }
  const gridGeometry = new BufferGeometry(); gridGeometry.setAttribute("position", new Float32BufferAttribute(linePoints, 3));
  const gridMaterial = new LineBasicMaterial({ color: "#dce3d8" });
  group.add(new LineSegments(gridGeometry, gridMaterial)); resources.push(gridGeometry, gridMaterial);
  let frame = 0;
  let targets: { x: number; y: number; cluster: TimelineDisplayCluster }[] = [];
  const draw = () => {
    frame = 0;
    if (disposed || document.hidden) return;
    try {
      group.updateMatrixWorld(true); camera.updateMatrixWorld(true);
      renderer.render(scene, camera);
      targets = batches.flatMap(batch => batch.clusters.map(cluster => {
        const position = chartPosition(cluster, input)!;
        const p = group.localToWorld(world(position.x, position.y)).project(camera);
        return { x: (p.x + 1) * width / 2, y: (1 - p.y) * height / 2, cluster };
      }));
      onLabels(tickAnchors.map(tick => {
        const p = group.localToWorld(tick.point.clone()).project(camera);
        return { x: (p.x + 1) * width / 2, y: (1 - p.y) * height / 2, text: tick.text, axis: tick.axis };
      }));
    } catch { onLost(); }
  };
  const schedule = () => { if (!disposed && !frame) frame = requestAnimationFrame(draw); };
  const resume = () => { if (!document.hidden) schedule(); };
  document.addEventListener("visibilitychange", resume);
  schedule();
  const raycaster = new Raycaster();
  return {
    perspective(enabled) { group.rotation.set(enabled ? -.16 : 0, enabled ? .26 : 0, 0); group.position.set(0, 0, 0); camera.zoom = 1; camera.updateProjectionMatrix(); schedule(); },
    rotate(dx, dy) { group.rotation.y = Math.max(-.45, Math.min(.45, group.rotation.y + dx * .003)); group.rotation.x = Math.max(-.3, Math.min(.3, group.rotation.x + dy * .003)); schedule(); },
    pan(dx, dy) { group.position.x = Math.max(-width / 2, Math.min(width / 2, group.position.x + dx / camera.zoom)); group.position.y = Math.max(-height / 2, Math.min(height / 2, group.position.y - dy / camera.zoom)); schedule(); },
    zoom(factor) { camera.zoom = Math.max(.8, Math.min(2, camera.zoom * factor)); camera.updateProjectionMatrix(); schedule(); },
    pick(x, y) {
      group.updateMatrixWorld(true); camera.updateMatrixWorld(true);
      raycaster.setFromCamera(new Vector2(x / width * 2 - 1, 1 - y / height * 2), camera);
      const hit = raycaster.intersectObjects(batches.map(batch => batch.mesh), false)[0];
      if (hit && hit.instanceId !== undefined) return batches.find(batch => batch.mesh === hit.object)?.clusters[hit.instanceId] ?? null;
      // Hollow origin markers remain selectable through their centres.
      let nearest: TimelineDisplayCluster | null = null, distance = 9 * 9;
      for (const target of targets) {
        const squared = (target.x - x) ** 2 + (target.y - y) ** 2;
        if (squared < distance) { distance = squared; nearest = target.cluster; }
      }
      return nearest;
    },
    dispose() {
      if (disposed) return; disposed = true; cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", resume);
      batches.forEach(batch => batch.mesh.dispose()); resources.forEach(resource => resource.dispose());
      void renderer.dispose().catch(() => {});
    },
  };
}
