/** 테스트·e2e 가짜 검출기 전용 합성 얼굴. 숨긴 정답 사상으로 MediaPipe와 같은 번호의 특징점 478개를 만든다.
 *  실제 얼굴 모양을 흉내 내지 않고, 시선 특징 계산(features.ts)이 쓰는 점들의 기하만 맞춘다. 프로덕션 코드에서 쓰지 않는다.
 *
 *  규약(D의 edgeLabel과 같음): 원본 프레임(좌우 반전 전)에서 사용자의 오른쪽은 x가 작은 쪽이다.
 *  - gazeX·yaw > 0: 사용자 오른쪽 · gazeY·pitch > 0: 아래쪽 (라디안)
 *  - 사용자가 자기 오른쪽을 보면 홍채 x가 작아지고, 고개를 오른쪽으로 돌리면 코끝 x가 작아진다 */

import { gazeFeatures, isFeatures, type GazeFeatures } from "./features";
import type { GroupedSample } from "./regression";
import type { LensSample } from "./lens";
import { PROTOCOL, collect, mockPanelRect, type Fixation, type FixationData, type Pose } from "./calibration";
import type { Frame } from "./sampler";

type Pt = { x: number; y: number };

export type FaceParams = {
  /** 시선 방향(세상 기준, 라디안). 눈의 머리 기준 회전 = 시선 − 고개 */
  gazeX: number;
  gazeY: number;
  yaw: number;
  pitch: number;
  roll?: number;
  /** 얼굴 폭(볼–볼, 프레임 너비 대비). 기본 0.2 */
  scale?: number;
  /** 얼굴 중심(정규화 좌표). 기본 (0.5, 0.5) */
  cx?: number;
  cy?: number;
  /** 모든 점에 더하는 가우스 잡음(프레임 너비 대비 표준편차) */
  noise?: number;
  seed?: number;
  /** 프레임 너비/높이. 기본 4/3 */
  aspect?: number;
  /** 눈 뜬 정도 배율(0이면 감음). 기본 1 */
  eyeOpen?: number;
  /** 홍채 이동의 2차 항(눈 폭 단위/rad²). 0이면 sin에 비례 */
  curvature?: number;
};

/** 홍채 이동 이득(눈 폭 단위/rad), 기본 눈 뜬 정도(눈꺼풀 거리/눈 폭) */
const GAIN = 0.4, OPEN = 0.3;

export function rng(seed: number) {
  let a = seed >>> 0 || 1;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return { next, gauss: () => Math.sqrt(-2 * Math.log(next() || 1e-12)) * Math.cos(2 * Math.PI * next()) };
}

export function syntheticFace(p: FaceParams): Pt[] {
  const s = p.scale ?? 0.2, aspect = p.aspect ?? 4 / 3, roll = p.roll ?? 0, c = p.curvature ?? 0;
  const cx = p.cx ?? 0.5, cyRel = (p.cy ?? 0.5) / aspect;
  const eyeYaw = p.gazeX - p.yaw, eyePitch = p.gazeY - p.pitch;
  const local: Pt[] = Array.from({ length: 478 }, () => ({ x: 0, y: 0 })); // 나머지 점은 얼굴 가운데
  // 고개: 코끝이 돌린 쪽으로 움직이고 눈도 조금 따라간다(볼·이마·턱은 그대로)
  local[1] = { x: -p.yaw * 0.5, y: 0.05 + p.pitch * 0.4 };
  local[10] = { x: 0, y: -0.75 };
  local[152] = { x: 0, y: 0.95 };
  local[234] = { x: -0.5, y: 0 };
  local[454] = { x: 0.5, y: 0 };
  const w = 0.2; // 눈 폭(얼굴 폭 단위)
  const ix = (-GAIN * Math.sin(eyeYaw) + c * eyeYaw * eyeYaw) * w;
  const iy = (GAIN * Math.sin(eyePitch) + c * eyePitch * eyePitch) * w;
  const gap = Math.max(0, OPEN * (1 - 1.2 * eyePitch) * (p.eyeOpen ?? 1)) * w;
  for (const [cxE, e] of [[-0.22, { a: 33, b: 133, up: 159, low: 145, iris: 468, ring: [469, 470, 471, 472] }],
    [0.22, { a: 362, b: 263, up: 386, low: 374, iris: 473, ring: [474, 475, 476, 477] }]] as const) {
    const ec = { x: cxE - p.yaw * 0.15, y: -0.22 + p.pitch * 0.05 };
    local[e.a] = { x: ec.x - w / 2, y: ec.y };
    local[e.b] = { x: ec.x + w / 2, y: ec.y };
    local[e.up] = { x: ec.x, y: ec.y - gap / 2 };
    local[e.low] = { x: ec.x, y: ec.y + gap / 2 };
    const ic = { x: ec.x + ix, y: ec.y + iy };
    local[e.iris] = ic;
    e.ring.forEach((i, k) => {
      const a = (k * Math.PI) / 2;
      local[i] = { x: ic.x + Math.cos(a) * 0.12 * w, y: ic.y + Math.sin(a) * 0.12 * w };
    });
  }
  const r = p.noise ? rng(p.seed ?? 1) : null;
  const cos = Math.cos(roll), sin = Math.sin(roll);
  return local.map(({ x, y }) => {
    const xr = (x * cos - y * sin) * s, yr = (x * sin + y * cos) * s; // 얼굴 폭 단위 → 프레임 너비 단위, 갸웃 회전
    const nx = r ? r.gauss() * p.noise! : 0, ny = r ? r.gauss() * p.noise! : 0;
    return { x: cx + xr + nx, y: (cyRel + yr + ny) * aspect };
  });
}

// ───────── 화면 응시 합성 데이터(테스트 도우미) ─────────

export const VIEW = { w: 1280, h: 720 };
/** 숨긴 기하: 눈이 뷰포트 가운데 앞, 뷰포트 너비의 distance배 거리에 있다고 보고 화면 점 → 시선 각도 */
export function screenToGaze(x: number, y: number, view = VIEW, distance = 1.8) {
  const d = distance * view.w;
  return { gazeX: Math.atan((x - view.w / 2) / d), gazeY: Math.atan((y - view.h / 2) / d) };
}

/** 보정 9점(뷰포트 비율), 가운데부터 뱀 순서 */
export const GRID9: [number, number][] = [[0.5, 0.5], [0.08, 0.08], [0.5, 0.08], [0.92, 0.08], [0.92, 0.5], [0.08, 0.5],
  [0.08, 0.92], [0.5, 0.92], [0.92, 0.92]];

/** 격자 지점을 보는 프레임 묶음. groupOffsetPx만큼 응시마다 고정된 치우침(특징으로 설명할 수 없음)을 정답에 더한다 */
export function syntheticGrid(o: { groups?: number; framesPerGroup?: number; groupOffsetPx?: number; curvature?: number;
  noise?: number; seed?: number; targets?: [number, number][]; view?: { w: number; h: number } } = {}): GroupedSample[] {
  const view = o.view ?? VIEW, seed = o.seed ?? 1;
  const targets = (o.targets ?? GRID9).slice(0, o.groups ?? 9);
  const out: GroupedSample[] = [];
  targets.forEach(([tx, ty], gi) => {
    const r = rng(seed * 7919 + gi);
    const a = r.next() * 2 * Math.PI, off = o.groupOffsetPx ?? 0;
    const label: [number, number] = [tx * view.w + Math.cos(a) * off, ty * view.h + Math.sin(a) * off];
    for (let fi = 0; fi < (o.framesPerGroup ?? 12); fi++) {
      const face = syntheticFace({ ...screenToGaze(tx * view.w, ty * view.h, view), yaw: 0, pitch: 0, curvature: o.curvature,
        noise: o.noise ?? 0.0001, seed: seed * 100_003 + gi * 101 + fi });
      const f = gazeFeatures(face, 640, 480);
      if (isFeatures(f)) out.push({ f, target: label, group: `g${seed}-${gi}` });
    }
  });
  return out;
}

// ───────── 렌즈 응시 합성 데이터(테스트 도우미) ─────────

/** 화면 위쪽 띠(뷰포트 위 2%)의 가운데를 볼 때의 세로 시선 각도 */
const topGaze = (view = VIEW) => screenToGaze(view.w / 2, 0.02 * view.h, view).gazeY;

/** 렌즈 응시(lensOffset: 화면 위쪽 띠 가운데보다 렌즈가 위에 있는 각도, 라디안. 0이면 위쪽 띠 가운데와 같은 곳)의 특징.
 *  gazeY를 주면 그 세로 각도를 본다(렌즈가 아닌 곳) */
export function lensFeatures(lensOffset: number, gazeY?: number) {
  return gazeFeatures(syntheticFace({ gazeX: 0, gazeY: gazeY ?? topGaze() - lensOffset, yaw: 0, pitch: 0 }), 640, 480) as GazeFeatures;
}
export const farFeatures = (): GazeFeatures => ({ ex: 3, ey: -3, open: 0.3, hx: 2, hy: 2, faceX: 0.5, faceY: 0.5, scale: 0.1, eyeGap: 0 });

/** 렌즈 응시 묶음 3개(정면, 고개 왼쪽, 오른쪽)와 화면 응시 묶음 16개(위쪽 띠 4개 + 나머지 격자 8개 + 고개 자세 4개) */
export function syntheticLens(o: { lensOffset: number; noise?: number; positives?: number; negatives?: number; seed?: number }): LensSample[] {
  const seed = o.seed ?? 1, noise = o.noise ?? 0.0002, view = VIEW;
  const lensGaze = { gazeX: 0, gazeY: topGaze(view) - o.lensOffset };
  const baseOpen = lensFeatures(o.lensOffset).open;
  const pos = [{ id: "lens-0", yaw: 0 }, { id: "lens-l", yaw: -0.15 }, { id: "lens-r", yaw: 0.15 }];
  const top: [number, number][] = [[0.35, 0.02], [0.5, 0.02], [0.65, 0.02], [0.5, 0.08]];
  // 실제 보정 순서처럼 화면 음성에도 고개 자세(4a: 가운데 점을 보며 고개 왼쪽·오른쪽·위·아래)를 넣는다.
  // 그래야 고개 방향만으로 렌즈 응시를 가려내는 지름길이 생기지 않는다
  const neg = [...top.map((t) => ({ t, topBand: true, yaw: 0, pitch: 0 })),
    ...GRID9.filter(([x, y]) => !(x === 0.5 && y === 0.08)).map((t) => ({ t, topBand: false, yaw: 0, pitch: 0 })),
    ...[[-0.15, 0], [0.15, 0], [0, -0.1], [0, 0.1]].map(([yaw, pitch]) => ({ t: [0.5, 0.5] as [number, number], topBand: false, yaw, pitch }))];
  const split = (total: number, parts: number, k: number) => Math.floor(total / parts) + (k < total % parts ? 1 : 0);
  const out: LensSample[] = [];
  const push = (gaze: { gazeX: number; gazeY: number }, yaw: number, pitch: number, lens: boolean, topBand: boolean, group: string,
    n: number, gi: number) => {
    for (let fi = 0; fi < n; fi++) {
      const f = gazeFeatures(syntheticFace({ ...gaze, yaw, pitch, noise, seed: seed * 100_003 + gi * 211 + fi }), 640, 480);
      if (isFeatures(f)) out.push({ f, openRatio: f.open / baseOpen, lens, topBand, group: `${seed}-${group}` });
    }
  };
  pos.forEach((g, k) => push(lensGaze, g.yaw, 0, true, false, g.id, split(o.positives ?? 36, pos.length, k), k));
  neg.forEach((g, k) => push(screenToGaze(g.t[0] * view.w, g.t[1] * view.h, view), g.yaw, g.pitch, false, g.topBand,
    `screen-${g.t[0]}-${g.t[1]}-${g.yaw}-${g.pitch}`, split(o.negatives ?? 192, neg.length, k), 100 + k));
  return out;
}

// ───────── 0단계 실행 전체의 합성 데이터(테스트 도우미) ─────────

/** 가운데를 보는 정면 얼굴 프레임 n개 */
export function fakeFrames(n: number, p: Partial<FaceParams> = {}): Frame[] {
  return Array.from({ length: n }, (_, i) => ({ t: i * 66, width: 640, height: 480, detectMs: 5,
    points: syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0, ...p }) }));
}

/** 안내를 따르는 가상 사용자의 고개·거리. 사용자의 왼쪽은 yaw < 0, 앞으로 기울이면 얼굴이 커진다 */
export const POSE_GEOMETRY: Record<Pose, { yaw: number; pitch: number; scale: number }> = {
  forward: { yaw: 0, pitch: 0, scale: 1 }, left: { yaw: -0.15, pitch: 0, scale: 1 }, right: { yaw: 0.15, pitch: 0, scale: 1 },
  up: { yaw: 0, pitch: -0.1, scale: 1 }, down: { yaw: 0, pitch: 0.1, scale: 1 }, near: { yaw: 0, pitch: 0, scale: 1.25 },
  far: { yaw: 0, pitch: 0, scale: 0.8 },
};

/** PROTOCOL 전체를 가상 사용자가 따라 한 결과. lensOffset: 렌즈가 화면 위쪽 띠 가운데보다 위에 있는 각도(라디안) */
export function syntheticRun(o: { noise?: number; lensOffset?: number; validRatio?: number; seed?: number;
  view?: { w: number; h: number }; override?: (fx: Fixation) => Partial<FaceParams> } = {}): FixationData[] {
  const view = o.view ?? VIEW, noise = o.noise ?? 0.0001, seed = o.seed ?? 1, valid = o.validRatio ?? 1;
  const lensGaze = { gazeX: 0, gazeY: topGaze(view) - (o.lensOffset ?? 0.12) };
  const r = rng(seed * 31 + 7);
  return PROTOCOL.map((fx, k) => {
    const pose = POSE_GEOMETRY[fx.pose];
    let target: [number, number] | undefined, panelRect;
    if (fx.target === "panel") {
      panelRect = mockPanelRect(view, fx.panelPx!);
      target = [panelRect.left + panelRect.width / 2, panelRect.top + panelRect.height / 2];
    } else if (fx.target === "typing") target = [view.w / 2, view.h * 0.8];
    else if (typeof fx.target === "object") target = [fx.target.x * view.w, fx.target.y * view.h];
    const gaze = fx.target === "lens" ? lensGaze : screenToGaze(target![0], target![1], view);
    const n = fx.role === "rate" || fx.role === "typing" ? 10 : 15;
    const frames: Frame[] = Array.from({ length: n }, (_, i) => ({ t: i * 66, width: 640, height: 480, detectMs: 5,
      points: r.next() < valid ? syntheticFace({ ...gaze, yaw: pose.yaw, pitch: pose.pitch, scale: 0.2 * pose.scale, noise, ...o.override?.(fx),
        seed: seed * 100_003 + k * 101 + i }) : null }));
    const rate = fx.hz ? { targetHz: fx.hz, achievedHz: fx.hz, detectP50: 5, detectP95: 8, busyPct: 8, lagP95: 10, longTasks: 0 } : undefined;
    return collect(frames, fx, { target: fx.target === "lens" || fx.target === "typing" ? undefined : target, rate, panelRect });
  });
}

