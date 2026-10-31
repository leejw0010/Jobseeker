/** 테스트·e2e 가짜 검출기 전용 합성 얼굴. 숨긴 정답 사상으로 MediaPipe와 같은 번호의 특징점 478개를 만든다.
 *  실제 얼굴 모양을 흉내 내지 않고, 시선 특징 계산(features.ts)이 쓰는 점들의 기하만 맞춘다. 프로덕션 코드에서 쓰지 않는다.
 *
 *  규약(D의 edgeLabel과 같음): 원본 프레임(좌우 반전 전)에서 사용자의 오른쪽은 x가 작은 쪽이다.
 *  - gazeX·yaw > 0: 사용자 오른쪽 · gazeY·pitch > 0: 아래쪽 (라디안)
 *  - 사용자가 자기 오른쪽을 보면 홍채 x가 작아지고, 고개를 오른쪽으로 돌리면 코끝 x가 작아진다 */

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
