import type { CameraDiag } from "../video/debug";
import { edgeLabel } from "../video/metrics";

const n3 = (v: number) => v.toFixed(3);

/** 개발 전용 카메라 진단. 실제 웹캠으로 지표를 점검할 때(docs/progress.md 수동 검증) 쓴다. 저장·전송하지 않는다 */
export default function CameraDiagnostics({ diag }: { diag: CameraDiag }) {
  const { sample: s, width, height, counts: c } = diag;
  const o = s?.overshoot;
  return (
    <div className="small muted camera-diagnostics" aria-label="카메라 진단">
      <b>카메라 진단(개발용)</b>
      <div>카메라 해상도 {width}×{height} · 상태 {s?.state ?? "–"}</div>
      {o && <>
        <div>넘은 정도(원본 프레임 기준): 위 {n3(o.top)} · 아래 {n3(o.bottom)} · 원본 왼쪽 {n3(o.left)} · 원본 오른쪽 {n3(o.right)}</div>
        <div>미리보기 기준: {edgeLabel(o)} · 핵심 부위(눈·코·입) 모두 프레임 안: {s?.coreInside ? "예" : "아니요"}</div>
      </>}
      <div>표본 in {c.in} · edge {c.edge}(그중 핵심 부위 안 {c.edgeCore}) · none {c.none}</div>
    </div>
  );
}
