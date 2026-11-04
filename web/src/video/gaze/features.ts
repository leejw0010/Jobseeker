/** 시선 특징(설계 4절). MediaPipe 특징점(정규화 좌표, 원본 프레임 = 좌우 반전 전)에서 눈·홍채·눈꺼풀·고개 특징을 뽑는다.
 *  정규화 좌표는 x를 프레임 너비로, y를 높이로 나눈 값이라 픽셀 좌표로 바꾼 뒤 거리·각도를 잰다(4:3이 아니어도 비율 유지).
 *  특징점은 계산 후 버리고 이 숫자들만 남긴다(좌표·특징점은 저장·전송하지 않는다). */
import { EYE_GAP_MAX, EYE_MARGIN } from "./constants";

type Pt = { x: number; y: number };

export type GazeFeatures = {
  /** 홍채 중심의 눈 좌표계 위치(눈 폭 단위, 두 눈 평균). x는 원본 프레임 오른쪽(+x)이 +, y는 아래가 + */
  ex: number;
  ey: number;
  /** 눈꺼풀 거리 / 눈 폭(두 눈 평균, 원시값). 기준값 나눗셈은 보정 단계에서 한다 */
  open: number;
  /** 고개 방향 특징: 코끝의 얼굴 좌표계 위치(좌우는 볼 사이 폭, 상하는 이마–턱 길이에 대한 비율) */
  hx: number;
  hy: number;
  /** 두 눈 중심의 프레임 내 위치(정규화 좌표)와 눈 사이 거리 / 프레임 너비. 자세가 바뀌었는지만 판정한다 */
  faceX: number;
  faceY: number;
  scale: number;
  /** 두 눈 홍채 위치의 차이(눈 폭 단위). 크면 한쪽 눈 추적이 불안정하다 */
  eyeGap: number;
};
export type FeatureInvalid = { invalid: "no_face" | "eyes_outside" | "eyes_unreliable" | "invalid_resolution" | "nonfinite_geometry" };

// MediaPipe Face Mesh 번호(좌우는 피사체 기준). 각 눈은 원본 프레임 왼쪽 끝 → 오른쪽 끝 순서
const RIGHT_EYE = { a: 33, b: 133, up: 159, low: 145, iris: 468, ring: [469, 470, 471, 472] };
const LEFT_EYE = { a: 362, b: 263, up: 386, low: 374, iris: 473, ring: [474, 475, 476, 477] };
const NOSE = 1, TOP = 10, CHIN = 152, CHEEK_A = 234, CHEEK_B = 454;
const EYE_POINTS = [RIGHT_EYE, LEFT_EYE].flatMap((e) => [e.a, e.b, e.up, e.low, e.iris, ...e.ring]);

const sub = (p: Pt, q: Pt): Pt => ({ x: p.x - q.x, y: p.y - q.y });
const dot = (p: Pt, q: Pt) => p.x * q.x + p.y * q.y;
const len = (p: Pt) => Math.hypot(p.x, p.y);
const mid = (p: Pt, q: Pt): Pt => ({ x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 });

function eye(px: (i: number) => Pt, e: typeof RIGHT_EYE) {
  const a = px(e.a), b = px(e.b);
  const width = len(sub(b, a));
  const ux = { x: (b.x - a.x) / width, y: (b.y - a.y) / width };
  const uy = { x: -ux.y, y: ux.x }; // 눈꼬리 축에 수직(아래가 +)
  const c = mid(a, b);
  const iris = sub(px(e.iris), c);
  return { ex: dot(iris, ux) / width, ey: dot(iris, uy) / width, open: len(sub(px(e.up), px(e.low))) / width, center: c, width };
}

/** 한 프레임의 특징점 → 시선 특징. 얼굴이 없거나, 눈이 프레임 밖이거나, 두 눈이 서로 맞지 않으면 이유를 돌려준다 */
export function gazeFeatures(points: Pt[] | null | undefined, width: number, height: number): GazeFeatures | FeatureInvalid {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return { invalid: "invalid_resolution" };
  if (!points?.length) return { invalid: "no_face" };
  if (points.some((p) => !p || !Number.isFinite(p.x) || !Number.isFinite(p.y))) return { invalid: "nonfinite_geometry" };
  if (points.length < 478) return { invalid: "eyes_unreliable" };
  const inside = (p: Pt) => p.x >= EYE_MARGIN && p.x <= 1 - EYE_MARGIN && p.y >= EYE_MARGIN && p.y <= 1 - EYE_MARGIN;
  if (!EYE_POINTS.every((i) => inside(points[i]))) return { invalid: "eyes_outside" };
  const px = (i: number): Pt => ({ x: points[i].x * width, y: points[i].y * height });
  const r = eye(px, RIGHT_EYE), l = eye(px, LEFT_EYE);
  if (!(r.width > 0 && l.width > 0)) return { invalid: "eyes_unreliable" };
  const eyeGap = Math.max(Math.abs(r.ex - l.ex), Math.abs(r.ey - l.ey));
  if (eyeGap > EYE_GAP_MAX) return { invalid: "eyes_unreliable" };
  // 고개 방향: 볼–볼 축과 그 수직축으로 이룬 얼굴 좌표계에서 코끝 위치(갸웃해도 같은 값)
  const ca = px(CHEEK_A), cb = px(CHEEK_B), top = px(TOP), chin = px(CHIN), nose = px(NOSE);
  const faceW = len(sub(cb, ca));
  const fx = { x: (cb.x - ca.x) / faceW, y: (cb.y - ca.y) / faceW };
  const fy = { x: -fx.y, y: fx.x };
  const faceH = dot(sub(chin, top), fy);
  if (!(faceW > 0 && faceH > 0)) return { invalid: "eyes_unreliable" };
  const center = mid(r.center, l.center);
  const result: GazeFeatures = {
    ex: (r.ex + l.ex) / 2,
    ey: (r.ey + l.ey) / 2,
    open: (r.open + l.open) / 2,
    hx: dot(sub(nose, mid(ca, cb)), fx) / faceW,
    hy: dot(sub(nose, top), fy) / faceH,
    faceX: center.x / width,
    faceY: center.y / height,
    scale: len(sub(l.center, r.center)) / width,
    eyeGap,
  };
  return Object.values(result).every(Number.isFinite) ? result : { invalid: "nonfinite_geometry" };
}

export const isFeatures = (f: GazeFeatures | FeatureInvalid): f is GazeFeatures => !("invalid" in f);
