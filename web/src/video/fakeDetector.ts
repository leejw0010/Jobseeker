import type { FaceDetector } from "./detector";
import { CORE_LANDMARKS, type Point } from "./metrics";
import type { Pose } from "./gaze/calibration";
import { POSE_GEOMETRY, screenToGaze, syntheticFace } from "./gaze/synthetic";

/** e2e 전용 가짜 검출기. 모델을 내려받지 않고 정해진 순서로 특징점을 돌려준다.
 *  localStorage "e2e-face-detector"가 "fail"이면 모델을 불러오지 못한 경우를, "edge-top"이면 카메라 가까이 앉아
 *  이마 위만 프레임 밖이고 눈·코·입은 안에 있는 얼굴을 흉내 낸다. "gaze"·"gaze-inseparable"·"gaze-noisy"는 시선 실험실용 가상 사용자다. */
export async function loadFakeDetector(): Promise<FaceDetector> {
  const mode = localStorage.getItem("e2e-face-detector");
  if (mode === "fail") throw new Error("fake model load failure");
  if (mode === "edge-top") return { detect: () => foreheadCut(), close: () => {} };
  if (mode === "gaze" || mode === "gaze-inseparable" || mode === "gaze-noisy") return gazeUser(mode);
  let n = 0;
  return {
    detect: () => {
      const step = n++ % 20; // 20번 중 앞 14번은 정면, 2번은 고개를 돌림, 4번은 얼굴 없음
      return step < 14 ? face(0) : step < 16 ? face(0.08) : null;
    },
    close: () => {},
  };
}

/** 화면 가운데 얼굴. shift만큼 코끝을 옆으로 옮긴다(얼굴 폭 0.2에 대해 0.08 = 40%) */
function face(shift: number): Point[] {
  const pts: Point[] = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5 }));
  pts[1] = { x: 0.5 + shift, y: 0.5 };
  pts[10] = { x: 0.5, y: 0.35 };
  pts[152] = { x: 0.5, y: 0.7 };
  pts[234] = { x: 0.4, y: 0.5 };
  pts[454] = { x: 0.6, y: 0.5 };
  return pts;
}

/** 이마 위(10)만 y = -0.03으로 프레임 위를 넘고, 핵심 부위(CORE_LANDMARKS)는 얼굴 안쪽에 있는 얼굴 */
function foreheadCut(): Point[] {
  const pts = face(0);
  for (const i of CORE_LANDMARKS) pts[i] = { x: 0.5, y: 0.45 };
  pts[10] = { x: 0.5, y: -0.03 };
  return pts;
}

/** 시선 실험실 e2e: 화면에 표시된 대상(data-gaze-target 요소의 가운데, data-gaze-lens면 카메라 렌즈)을 안내된 자세
 *  (data-gaze-pose)로 보는 가상 사용자. 렌즈는 화면 위쪽 띠 가운데보다 0.12rad 위("gaze-inseparable"이면 위쪽 띠 가운데와 같은 곳).
 *  "gaze-noisy"는 특징점 흔들림이 커서 화면 좌표 추정이 실패해야 한다 */
function gazeUser(mode: "gaze" | "gaze-inseparable" | "gaze-noisy"): FaceDetector {
  let n = 0;
  return {
    detect: () => {
      const view = { w: innerWidth, h: innerHeight };
      const lens = document.querySelector<HTMLElement>("[data-gaze-lens]");
      const el = lens ?? document.querySelector<HTMLElement>("[data-gaze-target]");
      const pose = POSE_GEOMETRY[(el?.dataset.gazePose as Pose | undefined) ?? "forward"] ?? POSE_GEOMETRY.forward;
      let gaze = screenToGaze(view.w / 2, view.h / 2, view);
      if (lens) {
        const top = screenToGaze(view.w / 2, 0.02 * view.h, view);
        gaze = mode === "gaze-inseparable" ? top : { gazeX: 0, gazeY: top.gazeY - 0.12 };
      } else if (el) {
        const r = el.getBoundingClientRect();
        gaze = screenToGaze(r.left + r.width / 2, r.top + r.height / 2, view);
      }
      return syntheticFace({ ...gaze, yaw: pose.yaw, pitch: pose.pitch, scale: 0.2 * pose.scale,
        noise: mode === "gaze-noisy" ? 0.003 : 0.0001, seed: ++n });
    },
    close: () => {},
  };
}

