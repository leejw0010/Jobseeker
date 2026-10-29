import type { FaceDetector } from "./detector";
import type { Point } from "./metrics";

/** e2e 전용 가짜 검출기. 모델을 내려받지 않고 정해진 순서로 특징점을 돌려준다.
 *  localStorage "e2e-face-detector"가 "fail"이면 모델을 불러오지 못한 경우를 흉내 낸다. */
export async function loadFakeDetector(): Promise<FaceDetector> {
  if (localStorage.getItem("e2e-face-detector") === "fail") throw new Error("fake model load failure");
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
