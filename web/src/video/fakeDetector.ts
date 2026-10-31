import type { FaceDetector } from "./detector";
import { CORE_LANDMARKS, type Point } from "./metrics";

/** e2e 전용 가짜 검출기. 모델을 내려받지 않고 정해진 순서로 특징점을 돌려준다.
 *  localStorage "e2e-face-detector"가 "fail"이면 모델을 불러오지 못한 경우를, "edge-top"이면 카메라 가까이 앉아
 *  이마 위만 프레임 밖이고 눈·코·입은 안에 있는 얼굴을 흉내 낸다. */
export async function loadFakeDetector(): Promise<FaceDetector> {
  const mode = localStorage.getItem("e2e-face-detector");
  if (mode === "fail") throw new Error("fake model load failure");
  if (mode === "edge-top") return { detect: () => foreheadCut(), close: () => {} };
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
