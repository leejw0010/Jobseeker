import { useState } from "react";
import type { PracticeAnswer } from "../types";
import { clearSessionVideo, combineSummaries, sessionVideo, type SegmentSummary } from "../video/metrics";

const sec = (ms: number) => {
  const s = Math.round(ms / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`;
};
const pct = (part: number, whole: number) => (whole > 0 ? `${Math.round((part / whole) * 100)}%` : "–");

/** 회고 화면: 이 탭에서 잰 카메라 자세 분석 결과. 카메라를 켜지 않았거나 새로고침했으면 보이지 않는다 */
export default function VideoReportCard({ sessionId, answers }: { sessionId: string; answers: PracticeAnswer[] }) {
  const [report, setReport] = useState(() => sessionVideo(sessionId));
  if (!report?.size) return null;
  const rows = answers.map((a, i) => ({ a, i, s: report.get(a.id) })).filter((r): r is { a: PracticeAnswer; i: number; s: SegmentSummary } => !!r.s);
  const all = combineSummaries(rows.map((r) => r.s));
  return (
    <section className="card video-report">
      <div className="row"><h2 className="grow" style={{ margin: 0 }}>카메라 자세 분석</h2><span className="chip">이 탭에만 보관</span></div>
      <p className="small muted">답변한 {rows.length}개, 모두 {sec(all.totalMs)} 동안 초당 약 4번 확인한 값이에요(표본 {all.samples}개). 영상은 저장하지 않았고, 이 수치도 새로고침하거나 탭을 닫으면 사라져요.</p>
      <dl className="video-metrics">
        <dt>얼굴 검출 비율</dt>
        <dd><b>{pct(all.detectedMs, all.totalMs)}</b> · 분석한 시간 중 얼굴 특징점을 찾은 시간</dd>
        <dt>화면을 벗어난 시간</dt>
        <dd><b>{sec(all.offMs)}</b> ({pct(all.offMs, all.totalMs)}) · 얼굴을 찾지 못했거나 얼굴 일부가 화면 밖에 있던 시간. 1초 이상 벗어난 횟수 {all.offEpisodes}번, 가장 길게 벗어난 시간 {sec(all.longestOffMs)}</dd>
        <dt>고개를 좌우로 돌린 시간</dt>
        <dd>{all.headMs ? <><b>{pct(all.turnedMs, all.headMs)}</b> · 각 답변의 평소 방향보다 크게 돌린 시간의 비율</> : "측정한 시간이 짧아 계산하지 않았어요"}</dd>
        <dt>고개를 숙인 시간</dt>
        <dd>{all.headMs ? <><b>{pct(all.downMs, all.headMs)}</b> · 각 답변의 평소 방향보다 크게 숙인 시간의 비율</> : "측정한 시간이 짧아 계산하지 않았어요"}</dd>
      </dl>
      <div className="table-scroll">
        <table>
          <thead><tr><th>질문</th><th>분석 시간</th><th>얼굴 검출</th><th>벗어난 시간</th><th>좌우 회전</th><th>숙임</th></tr></thead>
          <tbody>
            {rows.map(({ a, i, s }) => (
              <tr key={a.id}>
                <td><a href={`#answer-${a.id}`}>Q{i + 1}</a> <span className="small muted">{a.question.text}</span></td>
                <td>{sec(s.totalMs)}</td>
                <td>{pct(s.detectedMs, s.totalMs)}</td>
                <td>{sec(s.offMs)}</td>
                <td>{s.headMs ? pct(s.turnedMs, s.headMs) : "–"}</td>
                <td>{s.headMs ? pct(s.downMs, s.headMs) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="bullets small muted">
        <li>고개 방향은 코끝이 양 볼 사이, 이마와 턱 사이 어디에 있는지로 대략 추정해요. 각 답변 동안의 중앙값을 기준으로 한 상대적인 변화라서, 처음부터 숙이고 있었다면 숙임으로 잡히지 않아요. ‘–’는 얼굴이 화면 안에 있던 시간이 짧아 기준을 잡지 못한 경우예요.</li>
        <li>시선 추적이 아니에요. 화면을 보는지, 카메라를 보는지는 알 수 없어요. 글로 답할 때는 자판을 내려다본 시간이 숙임으로 잡힐 수 있어요.</li>
        <li>조명, 카메라 위치, 안경 등에 따라 값이 달라질 수 있어요. 자신감·감정·합격 가능성은 판단하지 않아요.</li>
      </ul>
      <button onClick={() => { clearSessionVideo(sessionId); setReport(undefined); }}>이 결과 지우기</button>
    </section>
  );
}
