import { Suspense, lazy } from "react";
import { CAMERA_DEBUG, type CameraDiag } from "../video/debug";
import type { CameraStatus } from "./useFaceAnalysis";
import { edgeLabel, type FaceState, type Overshoot } from "../video/metrics";

const FACE_LABEL: Record<FaceState, string> = {
  in: "얼굴이 화면 안에 있어요",
  edge: "얼굴 일부가 화면 밖에 있어요",
  none: "얼굴을 찾지 못했어요",
};

// 개발 전용 진단. 프로덕션 빌드에서는 CAMERA_DEBUG가 false라 이 모듈을 불러오지 않는다
const Diagnostics = CAMERA_DEBUG ? lazy(() => import("./CameraDiagnostics")) : null;

/** 면접 화면의 선택 기능: 카메라 자세 분석 동의·켜기/끄기와 미리보기 */
export default function CameraPanel({ status, error, face, edge, diag, onEnable, onDisable, attachVideo, liveHints=true, onLiveHintsChange }: {
  liveHints?: boolean;
  onLiveHintsChange?: (enabled:boolean)=>void;
  status: CameraStatus;
  error: string | null;
  face: FaceState | null;
  /** edge일 때 넘은 쪽(원본 프레임 기준). 문구는 미리보기(좌우 반전) 기준으로 바꿔 보여 준다 */
  edge: Overshoot | null;
  diag: CameraDiag | null;
  onEnable: () => void;
  onDisable: () => void;
  attachVideo: (el: HTMLVideoElement | null) => void;
}) {
  return (
    <section className="card camera-panel">
      <div className="row"><h2 className="grow" style={{ margin: 0 }}>카메라 자세 분석</h2><span className="chip">선택</span></div>
      {status === "on" ? (
        <div className="row camera-live">
          <video ref={attachVideo} className="camera-preview" autoPlay muted playsInline aria-label="내 카메라 미리보기" />
          <div className="grow">
            {onLiveHintsChange&&<label className="check-label"><input type="checkbox" checked={liveHints} onChange={e=>onLiveHintsChange(e.target.checked)}/>실시간 자세 힌트</label>}
            {liveHints&&<p role="status" className={face === "in" ? "small" : "small warn-text"}>{face === "edge" && edge ? edgeLabel(edge) : face ? FACE_LABEL[face] : "카메라 화면을 기다리는 중…"}</p>}
            <p className="small muted">녹음으로 답변하는 동안만 수치를 기록해요. 영상은 저장하거나 보내지 않아요.</p>
            <button onClick={onDisable}>카메라 끄기</button>
            {Diagnostics && diag && <Suspense fallback={null}><Diagnostics diag={diag} /></Suspense>}
          </div>
        </div>
      ) : <>
        <ul className="bullets small">
          <li>켜면 녹음으로 답변하는 동안 브라우저 안에서 얼굴 특징점을 찾아 <b>얼굴 검출 비율, 얼굴을 찾지 못한 시간, 얼굴 일부가 프레임 밖에 있던 시간, 고개 좌우 회전·숙임의 상대적인 변화</b>를 재요. 결과는 면접을 마친 뒤 회고 화면에 보여 줘요.</li>
          <li>영상과 이미지는 저장하거나 서버·OpenAI로 보내지 않아요. 결과 수치도 이 탭의 메모리에만 두고, 새로고침하거나 탭을 닫으면 사라져요.</li>
          <li>분석 모델(MediaPipe Face Landmarker)은 켤 때 Google 서버에서 내려받아요. MediaPipe는 영상을 보내지 않지만 기능의 성능·사용 지표를 Google에 보낼 수 있어요.</li>
          <li>시선 추적이 아니에요. 자신감·감정·합격 가능성은 판단하지 않아요.</li>
          <li>켜지 않아도 면접 연습은 똑같이 할 수 있어요.</li>
        </ul>
        {error && <p className="warn-text" role="alert">{error}</p>}
        <button disabled={status === "starting"} onClick={onEnable}>{status === "starting" ? "카메라와 분석 모델을 준비하는 중…" : "동의하고 카메라 켜기"}</button>
      </>}
    </section>
  );
}
