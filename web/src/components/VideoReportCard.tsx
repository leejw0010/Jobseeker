import { createArtifact, downloadArtifacts, EXPORT_NOTICE, faceMetrics } from "../validation/artifact";
import { useState } from "react";
import type { PracticeAnswer } from "../types";
import { clearSessionVideo, combineSummaries, getVideoSegments, getVideoRunId, getVideoSegmentMetadata, videoDiagnostics, type SegmentSummary } from "../video/metrics";

const sec = (ms: number) => {
  const s = Math.round(ms / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`;
};
const pct = (part: number, whole: number) => (whole > 0 ? `${Math.round((part / whole) * 100)}%` : "–");

/** 회고 화면: 이 탭에서 잰 카메라 자세 분석 결과. 카메라를 켜지 않았거나 새로고침했으면 보이지 않는다 */
export default function VideoReportCard({ sessionId, answers, onCleared }: { sessionId: string; answers: PracticeAnswer[]; onCleared?:()=>void }) {
  const [removed,setRemoved] = useState(false);
  const [condition,setCondition]=useState("unspecified");
  if (removed) return null;
  const rows = answers.map((a, i) => ({ a, i, s: a.recorded_at ? getVideoSegments(sessionId,a.id,a.recorded_at) : undefined })).filter((r): r is { a: PracticeAnswer; i: number; s: SegmentSummary } => !!r.s);
  if(!rows.length) return null;
  const all = combineSummaries(rows.map((r) => r.s));
  const unanalyzed = Math.max(0, all.answerMs - all.analyzedMs);
  return (
    <section className="card video-report">
      <div className="row"><h2 className="grow" style={{ margin: 0 }}>카메라 자세 분석</h2><span className="chip">이 탭에만 보관</span></div>
      <p className="small muted">
        답변 {rows.length}개, 답변 시간 모두 {sec(all.answerMs)} 중 {sec(all.analyzedMs)}를 분석했어요(초당 약 4번, 표본 {all.samples}개).
        {unanalyzed >= 1000 && <> 분석하지 못한 시간 {sec(unanalyzed)}(탭이 가려졌거나, 카메라 화면이 준비되지 않았거나, 검출이 멈췄거나, 카메라를 끈 시간)은 아래 수치에 넣지 않았어요.</>}
        {" "}영상은 저장하지 않았고, 이 수치도 새로고침하거나 탭을 닫으면 사라져요.
      </p>
      <ul className="small muted">{videoDiagnostics(all).comments.map((c,i)=><li key={i}>{c}</li>)}</ul>
      <dl className="video-metrics">
        <dt>얼굴 검출 비율</dt>
        <dd><b>{pct(all.detectedMs, all.analyzedMs)}</b> · 분석한 시간 중 얼굴 특징점을 찾은 시간의 비율(얼굴 일부가 프레임 밖이었던 시간 포함)</dd>
        <dt>얼굴을 찾지 못한 시간</dt>
        <dd><b>{sec(all.noneMs)}</b> ({pct(all.noneMs, all.analyzedMs)}) · 분석한 시간 중 얼굴 특징점을 찾지 못한 시간. 자리를 비웠을 수도 있지만 조명·각도·가림 때문에 검출하지 못했을 수도 있어요. 1초 이상 이어진 횟수 {all.noneEpisodes}번, 가장 길게 이어진 시간 {sec(all.longestNoneMs)}</dd>
        <dt>얼굴 일부가 프레임 밖</dt>
        <dd><b>{sec(all.edgeMs)}</b> ({pct(all.edgeMs, all.analyzedMs)}) · 얼굴은 찾았지만 이마·턱·볼 가장자리 일부가 카메라 프레임 밖에 있던 시간(검출 비율에 포함)</dd>
        <dt>고개를 좌우로 돌린 시간</dt>
        <dd>{all.headMs ? <><b>{pct(all.turnedMs, all.headMs)}</b> · 각 답변의 평소 방향보다 크게 돌린 시간의 비율</> : "측정한 시간이 짧아 계산하지 않았어요"}</dd>
        <dt>고개를 숙인 시간</dt>
        <dd>{all.headMs ? <><b>{pct(all.downMs, all.headMs)}</b> · 각 답변의 평소 방향보다 크게 숙인 시간의 비율</> : "측정한 시간이 짧아 계산하지 않았어요"}</dd>
      </dl>
      <div className="table-scroll">
        <table>
          <thead><tr><th>질문</th><th>답변 시간</th><th>분석한 시간</th><th>얼굴 검출</th><th>찾지 못한 시간</th><th>일부 프레임 밖</th><th>좌우 회전</th><th>숙임</th></tr></thead>
          <tbody>
            {rows.map(({ a, i, s }) => (
              <tr key={a.id}>
                <td><a href={`#answer-${a.id}`}>Q{i + 1}</a> <span className="small muted">{a.question.text}</span></td>
                <td>{sec(s.answerMs)}</td>
                <td>{sec(s.analyzedMs)}</td>
                <td>{pct(s.detectedMs, s.analyzedMs)}</td>
                <td>{sec(s.noneMs)}</td>
                <td>{sec(s.edgeMs)}</td>
                <td>{s.headMs ? pct(s.turnedMs, s.headMs) : "–"}</td>
                <td>{s.headMs ? pct(s.downMs, s.headMs) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="bullets small muted">
        <li>고개 방향은 코끝이 양 볼 사이, 이마와 턱 사이 어디에 있는지로 대략 추정해요. 각 답변 동안의 중앙값을 기준으로 한 상대적인 변화라서, 처음부터 숙이고 있었다면 숙임으로 잡히지 않아요. ‘–’는 얼굴이 화면 안에 있던 시간이 짧아 기준을 잡지 못한 경우예요.</li>
        <li>시선 추적이 아니에요. 화면을 보는지, 카메라를 보는지는 알 수 없어요. 글로 답한 답변은 측정하지 않아요.</li>
        <li>조명, 카메라 위치, 안경 등에 따라 값이 달라질 수 있어요. 자신감·감정·합격 가능성은 판단하지 않아요.</li>
      </ul>
      <label>검증 조건 <select value={condition} onChange={e=>setCondition(e.target.value)}><option value="unspecified">기록하지 않음</option><option value="face-in-frame">정면·프레임 안</option><option value="face-edge">얼굴 프레임 경계</option><option value="face-pose">고개 돌림·숙임</option><option value="low-light">저조도</option><option value="glasses">안경 조건</option></select></label>
      <p className="small muted">{EXPORT_NOTICE}</p>
      <button onClick={()=>downloadArtifacts(rows.map(({s,a})=>createArtifact("face",faceMetrics(s),{attempts:1,samples:s.samples,answerMs:s.answerMs,analyzedMs:s.analyzedMs},{runId:getVideoRunId(sessionId,a.id,a.recorded_at!),condition,delegate:getVideoSegmentMetadata(sessionId,a.id,a.recorded_at!)?.delegate,methodVersion:getVideoSegmentMetadata(sessionId,a.id,a.recorded_at!)?.methodVersion,cameraWidth:getVideoSegmentMetadata(sessionId,a.id,a.recorded_at!)?.cameraWidth,cameraHeight:getVideoSegmentMetadata(sessionId,a.id,a.recorded_at!)?.cameraHeight,verdicts:{quality:s.analyzedMs>0?"pass":"fail"}})))}>익명 얼굴 집계 내보내기(JSON)</button>
      <button onClick={() => { clearSessionVideo(sessionId); setRemoved(true); onCleared?.(); }}>이 결과 지우기</button>
    </section>
  );
}
