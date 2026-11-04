import type { FaceSample } from "./metrics";

/** 카메라 진단 표시(개발 전용). Vite 개발 서버에서 VITE_CAMERA_DEBUG=true일 때만 켜진다.
 *  프로덕션 빌드에서는 import.meta.env.DEV가 false로 고정돼 진단 코드가 번들에서 빠진다 */
export const CAMERA_DEBUG = import.meta.env.DEV && import.meta.env.VITE_CAMERA_DEBUG === "true";
/** 시선 분석 0단계 실험실(/dev/gaze-lab, 개발 전용). Vite 개발 서버에서 VITE_GAZE_LAB=true일 때만 경로와 화면을 불러온다 */
export const GAZE_LAB = import.meta.env.DEV && import.meta.env.VITE_GAZE_LAB === "true";

/** 이번 답변(답변 중이 아니면 카메라를 켠 뒤)의 상태별 표본 수. edgeCore: edge이면서 핵심 부위(눈·코·입)는 프레임 안 */
export type DiagCounts = { in: number; edge: number; none: number; edgeCore: number };
/** 화면에 보여 주기만 하고 저장·전송하지 않는다 */
export type CameraDiag = { sample: FaceSample | null; width: number; height: number; counts: DiagCounts };

export const emptyCounts = (): DiagCounts => ({ in: 0, edge: 0, none: 0, edgeCore: 0 });
