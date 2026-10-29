import wasmLoaderPath from "@mediapipe/tasks-vision/vision_wasm_internal.js?url";
import wasmBinaryPath from "@mediapipe/tasks-vision/vision_wasm_internal.wasm?url";
import type { Point } from "./metrics";

export type FaceDetector = { detect(video: HTMLVideoElement, timestampMs: number): Point[] | null; close(): void };

/** MediaPipe 공식 Face Landmarker 모델. 카메라 분석을 켤 때만 내려받는다(VITE_FACE_MODEL_URL로 바꿀 수 있음) */
const MODEL_URL = (import.meta.env.VITE_FACE_MODEL_URL as string | undefined)
  || "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

/** 얼굴 특징점 검출기를 만든다. 라이브러리는 이때 처음 불러오므로 카메라 분석을 켜지 않으면 받지 않는다.
 *  WASM은 이 앱과 함께 배포한 파일을 쓴다. GPU로 만들지 못하면 CPU로 다시 시도한다. */
export async function loadFaceDetector(): Promise<FaceDetector> {
  // e2e 전용(playwright.config.ts가 켬). 프로덕션 빌드에서는 조건이 false로 고정돼 이 분기가 빠진다
  if (import.meta.env.VITE_E2E_FAKE_FACE === "true") return (await import("./fakeDetector")).loadFakeDetector();
  const { FaceLandmarker } = await import("@mediapipe/tasks-vision");
  const create = (delegate: "GPU" | "CPU") => FaceLandmarker.createFromOptions({ wasmLoaderPath, wasmBinaryPath }, {
    baseOptions: { modelAssetPath: MODEL_URL, delegate },
    runningMode: "VIDEO",
    numFaces: 1,
  });
  const landmarker = await create("GPU").catch(() => create("CPU"));
  return {
    detect: (video, ts) => landmarker.detectForVideo(video, ts).faceLandmarks[0] ?? null,
    close: () => landmarker.close(),
  };
}
