import { useCallback, useEffect, useRef, useState } from "react";
import { downloadArtifacts, EXPORT_NOTICE, compatibleRepeatSpread, type ValidationArtifact } from "../validation/artifact";
import { gazeArtifact } from "../validation/gaze";
import { faceDetectorMetadata } from "../video/detector";
import CameraPanel from "../components/CameraPanel";
import { useFaceAnalysis } from "../components/useFaceAnalysis";
import {
  PROTOCOL, aggregate, collect, evaluateRun, mockPanelRect,
  type FeasibilityReport, type Fixation, type FixationData, type Rect, type Verdict,
} from "../video/gaze/calibration";
import { FEASIBILITY, MAX_RETRY, MIN_VALID } from "../video/gaze/constants";
import type { Frame } from "../video/gaze/sampler";
import { createCalibrationGuard, type CalibrationInvalid } from "../video/gaze/quality";
import "./GazeLab.css";

/** 시선 분석 0단계 실험실(개발 전용, /dev/gaze-lab). 기존 카메라 스트림·검출기를 그대로 쓰고,
 *  프레임·특징점·좌표는 이 탭 메모리에서만 계산한 뒤 버린다. 화면에는 집계 숫자와 판정만 보이고, 화면을 떠나면 모두 사라진다.
 *  판정은 1단계로 갈지 정하는 실험 기준이고 정확도 보장이 아니다(설계 13절). */

const E2E = import.meta.env.VITE_E2E_FAKE_FACE === "true";
/** e2e에서만 단계 시간을 줄이고, 빠른 가짜 검출기로 초당 60회 모은다 */
const timeScale = () => (E2E ? Number(localStorage.getItem("e2e-gaze-scale")) || 1 : 1);
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
/** 보정은 시작할 때의 뷰포트 기준이다. 크기·창 위치·배율이 바뀌면 그 실행은 무효 */
const geometry = () => [innerWidth, innerHeight, screenX, screenY, devicePixelRatio, window.visualViewport?.scale ?? 1].join(",");
const INVALID: Record<CalibrationInvalid, string> = {
  viewport_changed: "창 크기·위치·배율이 바뀌어 이번 시험은 무효예요.",
  resolution_changed: "카메라 해상도가 바뀌어 이번 시험은 무효예요.",
  invalid_resolution: "유효한 카메라 해상도를 확인할 수 없어 이번 시험은 무효예요.",
};
const REJECTED: Record<string, string> = { no_face: "얼굴 없음", eyes_outside: "눈이 프레임 밖", eyes_unreliable: "눈 추적 불안정",
  invalid_resolution: "해상도 무효", resolution_changed: "해상도 변경", nonfinite_geometry: "좌표·시각 비정상", blink: "눈 감김 후보" };
const VERDICT: Record<Verdict, string> = { pass: "통과", fail: "실패", inconclusive: "결론 없음" };
const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const num = (v: number | null | undefined, d = 0) => (v == null ? "–" : v.toFixed(d));
const worst = (vs: Verdict[]): Verdict => (vs.includes("fail") ? "fail" : vs.includes("inconclusive") ? "inconclusive" : "pass");

type Phase = "intro" | "running" | "invalid" | "done";
type Current = { fx: Fixation; panel?: Rect; target?: [number, number]; step: number; total: number };
type RunSummary = Record<string, number | string | null>;

export default function GazeLab() {
  const cam = useFaceAnalysis();
  const { subscribeFrames, setTargetHz, rateSnapshot } = cam;
  const [phase, setPhase] = useState<Phase>("intro");
  const [invalidReason, setInvalidReason] = useState<CalibrationInvalid>("viewport_changed");
  const [current, setCurrent] = useState<Current | null>(null);
  const [skipRate, setSkipRate] = useState(false);
  const [condition,setCondition]=useState("baseline");
  const [report, setReport] = useState<FeasibilityReport | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [videoSize, setVideoSize] = useState<{ w: number; h: number } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [artifacts,setArtifacts]=useState<ValidationArtifact[]>([]);
  const activeAttempt=useRef<{id:string;stopped:boolean;finish:(status:"complete"|"invalid"|"aborted"|"error",r?:FeasibilityReport,reason?:string)=>void}|null>(null);
  const alive = useRef(true);
  const size = useRef<{ w: number; h: number } | null>(null);
  // 개발 모드(StrictMode)는 마운트를 두 번 하므로 마운트할 때마다 다시 켠다. 화면을 떠나면 진행 중인 시험을 멈춘다
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  // 실제 카메라 해상도만 표시용으로 읽는다
  useEffect(() => subscribeFrames((f) => {
    if (size.current?.w === f.width && size.current?.h === f.height) return;
    size.current = { w: f.width, h: f.height };
    setVideoSize(size.current);
  }), [subscribeFrames]);

  const run = useCallback(async () => {
    const id=crypto.randomUUID();
    let observed=0;
    let stopCollection:(()=>void)|undefined;
    const attempt={id,stopped:false,finish:(status:"complete"|"invalid"|"aborted"|"error",r?:FeasibilityReport,reason?:string)=>{
      if(attempt.stopped)return;attempt.stopped=true;stopCollection?.();
      if(alive.current)setArtifacts(prev=>[...prev,gazeArtifact(id,status,r??null,E2E?"synthetic-signal":"human-device",faceDetectorMetadata().delegate,skipRate,reason?[reason]:[],condition,observed,size.current)]);
    }};
    activeAttempt.current=attempt;
    try {
    const k = timeScale(), collectHz = k < 1 ? 60 : 15;
    // 채점 좌표는 스크롤바를 뺀 화면 기준(시험 화면을 덮는 고정 레이어와 같은 크기)
    const view = { w: document.documentElement.clientWidth, h: document.documentElement.clientHeight };
    const guard = createCalibrationGuard(geometry(), size.current ? { width: size.current.w, height: size.current.h } : undefined);
    const queue = PROTOCOL.filter((f) => !(skipRate && (f.role === "rate" || f.role === "typing"))).map((fx) => ({ fx, attempt: 0 }));
    const data: FixationData[] = [];
    setReport(null);
    setCopied(null);
    setPhase("running");
    for (let i = 0; i < queue.length; i++) {
      const { fx, attempt: retryAttempt } = queue[i];
      const panel = fx.target === "panel" ? mockPanelRect(view, fx.panelPx!) : undefined;
      const target: [number, number] | undefined = panel ? [panel.left + panel.width / 2, panel.top + panel.height / 2]
        : typeof fx.target === "object" ? [fx.target.x * view.w, fx.target.y * view.h] : undefined;
      setCurrent({ fx, panel, target, step: i + 1, total: queue.length });
      setTargetHz(fx.hz ?? collectHz);
      await sleep(fx.settleMs * k);
      const frames: Frame[] = [];
      if (!alive.current || attempt.stopped) { attempt.finish("aborted"); return; }
      const stop = subscribeFrames((f) => {
        observed++;
        guard.check(geometry(), { width: f.width, height: f.height });
        // A fixation lasts at most 20sec. Guard against a stalled timer retaining raw frames indefinitely.
        if (frames.length < 2400) frames.push(f);
      });
      stopCollection=stop;
      await sleep(fx.collectMs * k);
      stop();
      if (!alive.current || attempt.stopped) { attempt.finish("aborted"); return; }
      const invalid = guard.check(geometry());
      if (invalid) {
        attempt.finish("invalid",undefined,invalid);
        setInvalidReason(invalid);
        setTargetHz(4);
        setCurrent(null);
        setPhase("invalid");
        return;
      }
      const d = collect(frames, fx, { target, rate: fx.hz ? rateSnapshot() : undefined, panelRect: panel });
      // 유효 표본이 모자란 학습·검증 응시는 끝에 다시 잰다(최대 MAX_RETRY번)
      if (d.samples.length < MIN_VALID && retryAttempt < MAX_RETRY && (fx.role === "train" || fx.role === "validate")) {
        queue.push({ fx, attempt: retryAttempt + 1 });
      } else data.push(d);
    }
    setTargetHz(4);
    setCurrent(null);
    const r = evaluateRun(data, view, Object.fromEntries(FEASIBILITY.panel.heights.map((h) => [h, mockPanelRect(view, h)])));
    attempt.finish("complete",r);
    setReport(r);
    setRuns((prev) => [...prev, { run: prev.length + 1, ...aggregate(r), "camera.w": size.current?.w ?? null,
      "camera.h": size.current?.h ?? null, devicePixelRatio, skippedRate: skipRate ? "yes" : "no" }]);
    setPhase("done");
    } catch { attempt.finish("error",undefined,"model_error"); setTargetHz(4);setCurrent(null);setPhase("intro"); }
  }, [rateSnapshot, setTargetHz, skipRate, condition, subscribeFrames]);

  useEffect(()=>{if(phase==="running" && cam.status!=="on"){activeAttempt.current?.finish(cam.status==="error"?"error":"aborted",undefined,cam.status==="error"?"camera_error":"user_aborted");setTargetHz(4);setCurrent(null);setPhase("intro");}},[cam.status,phase,setTargetHz]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(artifacts, null, 1));
      setCopied("복사했어요. docs/progress.md의 G 0단계 표에 붙여 주세요.");
    } catch {
      setCopied("복사하지 못했어요. 아래 표의 숫자를 직접 옮겨 주세요.");
    }
  };

  return <>
    <h1>시선 실험실(개발 전용)</h1>
    <section className="card small">
      <p>시선 분석의 핵심 가정을 실제 웹캠으로 시험해요(설계 13절). 약 3분, 안내에 따라 점·카메라 렌즈·회색 칸을 봐요.</p>
      <ul className="bullets">
        <li>평소처럼 앉고(화면에서 약 50~60cm), 노트북 내장 카메라와 평소 조명을 써요. 안내가 없으면 고개는 그대로 두고 눈으로만 봐요.</li>
        <li>영상·얼굴 특징점·시선 좌표는 저장하거나 서버·외부로 보내지 않아요. 집계 숫자만 보여 주고, 이 화면을 떠나면 사라져요.</li>
        <li>시험 중에 창 크기를 바꾸거나 창을 옮기거나 확대/축소하면 그 실행은 무효가 돼요.</li>
        <li>판정은 다음 단계로 갈지 정하는 실험 기준이에요. 통과해도 정확도를 보장하지 않아요.</li>
      </ul>
      <p className="muted">뷰포트 {innerWidth}×{innerHeight} · 배율 {devicePixelRatio} · 카메라 {videoSize ? `${videoSize.w}×${videoSize.h}` : "–"}</p>
    </section>
    <CameraPanel status={cam.status} error={cam.error} face={cam.face} edge={cam.edge} diag={cam.diag}
      onEnable={() => void cam.enable()} onDisable={cam.disable} attachVideo={cam.attachVideo} />
    <section className="card">
      <div className="row">
        <label>검증 조건 <select value={condition} disabled={phase==="running"} onChange={e=>setCondition(e.target.value)}><option value="baseline">평소 조건</option><option value="low-light">저조도</option><option value="glasses">안경 조건 변경</option></select></label>
        <label className="check-label"><input type="checkbox" checked={skipRate} disabled={phase === "running"}
          onChange={(e) => setSkipRate(e.target.checked)} />주기 시험 건너뛰기</label>
        <button className="primary" disabled={cam.status !== "on" || phase === "running"} onClick={() => void run()}>시험 시작</button>
      </div>
      {phase === "invalid" && <div role="alert" className="warn-text">
        <p>{INVALID[invalidReason]} 보정은 시험을 시작할 때의 화면과 카메라 해상도 기준이라 처음부터 다시 해야 해요.</p>
        <button onClick={() => void run()}>처음부터 다시</button>
      </div>}
    </section>
    {phase === "running" && <button className="gaze-lab-stop" onClick={()=>{activeAttempt.current?.finish("aborted",undefined,"user_aborted");setTargetHz(4);setCurrent(null);setPhase("intro");}}>시험 중단</button>}
    {artifacts.length>0 && <section className="card"><h2>시도 집계</h2><p>전체 {artifacts.length}회 · 완료 {artifacts.filter(a=>a.status==="complete").length} · 무효 {artifacts.filter(a=>a.status==="invalid").length} · 중단 {artifacts.filter(a=>a.status==="aborted").length} · 오류 {artifacts.filter(a=>a.status==="error").length}</p><p>H2 전체 인증: 하지 않음. fresh 보정별 e50 너비 비율의 (최대−최소)/중앙값 참고값: {num(compatibleRepeatSpread(artifacts),3)} (동일 기록 조건의 최소 3회, 반복 안정성만 관찰)</p><p className="small muted">{EXPORT_NOTICE}</p><button onClick={()=>downloadArtifacts(artifacts)}>익명 Gaze 집계 내보내기(JSON)</button><button onClick={()=>{setArtifacts([]);setRuns([]);setReport(null);setPhase("intro");}}>모든 시도 지우기</button></section>}
    {phase === "done" && report && <Results report={report} runs={runs} onCopy={() => void copy()} copied={copied}
      onClear={() => { setArtifacts([]); setRuns([]); setReport(null); setPhase("intro"); }} />}
    {phase === "running" && current && <Overlay current={current} />}
  </>;
}

/** 시험 중 화면 전체: 지금 볼 대상 하나와 안내. 가짜 검출기(e2e)는 data-gaze-* 표시를 읽어 그곳을 본다 */
function Overlay({ current }: { current: Current }) {
  const { fx, panel, target } = current;
  // 채점에 쓰는 좌표를 그대로 그리고 표시해 둔다(점의 위치와 채점 좌표가 어긋나지 않게)
  const marker = { "data-gaze-pose": fx.pose, ...(target ? { "data-target-x": target[0], "data-target-y": target[1] } : {}) };
  return <div className="gaze-lab-overlay">
    <p className="gaze-lab-prompt" data-testid="lab-prompt">{fx.prompt} <span className="muted small">({current.step}/{current.total})</span></p>
    {fx.target === "lens" ? <div className="gaze-lab-lens" data-gaze-lens="" {...marker}>▲ 카메라 렌즈(외장 카메라면 그 렌즈)</div>
      : fx.target === "panel" && panel ? <div className="gaze-lab-panel" data-gaze-target="" {...marker}
        style={{ left: panel.left, top: panel.top, width: panel.width, height: panel.height }} />
        : fx.target === "typing" ? <textarea className="gaze-lab-typing" data-gaze-target="" {...marker} autoFocus
          placeholder="아무 글이나 입력하세요" aria-label="글 입력 시험" />
          : target ? <div className="gaze-lab-dot" data-gaze-target="" {...marker} style={{ left: target[0], top: target[1] }} /> : null}
  </div>;
}

function Results({ report: r, runs, onCopy, copied, onClear }: { report: FeasibilityReport; runs: RunSummary[];
  onCopy: () => void; copied: string | null; onClear: () => void }) {
  const distanceVerdict = worst(r.distance.map((d) => d.verdict));
  const rows: [string, Verdict, string][] = [
    ["H1 렌즈 대 화면 위쪽 (G1)", r.g1.verdict, `처음 보는 응시 AUC ${num(r.g1.valAuc, 2)} · 렌즈 정면 toward ${pct(r.g1.lensForward)} · 고개 돌림 toward ${pct(r.g1.lensTurned)} · 위쪽 띠 오판 ${pct(r.g1.topFalse)} · 화면 오판 ${pct(r.g1.screenFalse)} · (진단) 교차 검증 AUC ${num(r.g1.cvAuc, 2)}`],
    ["H2 화면 좌표 (G2)", r.g2.verdict, `처음 보는 4점 오차 중앙 ${num(r.g2.e50Px)}px(너비의 ${pct(r.g2.e50Pct)}) · 80% ${num(r.g2.e80Px)}px · 고개 돌림 오차 비율 ${num(r.g2.turnedRatio, 2)} · 유효 표본 ${pct(r.validRatio)} · 모델 ${r.g2.model ?? "–"} · 등급 ${r.g2.grade}${r.g2.reason ? ` · ${r.g2.reason}` : ""}`],
    ["질문 패널 영역 판정", r.panelVerdict, r.minPanelPx ? `쓸모 있는 최소 높이 ${r.minPanelPx}px` : "기준을 넘는 높이 없음(질문 영역 판정만 빼고 기타 화면·화면 밖은 유지)"],
    ["거리 변화", distanceVerdict, r.distance.map((d) => `${d.pose === "near" ? "앞으로" : "뒤로"}: 막힌 표본 ${pct(d.gated)}, 오차 비율 ${num(d.ratio, 2)}`).join(" · ")],
    ["표본 주기", r.rateVerdict, r.rates.some((x) => x.achievedHz !== null) ? `권장 후보 초당 ${r.recommendedHz}회` : "주기 시험을 건너뛰었어요"],
  ];
  const passCount = (key: string) => `${runs.filter((x) => x[key] === "pass").length}/${runs.length}`;
  return <section className="card">
    <h2>시험 결과</h2>
    <p className="small">이 판정은 1단계(본 구현)로 갈지 정하는 실험 기준이에요. 통과해도 실제 사용에 충분한 정확도를 보장하지 않아요. 한 사람·한 기기·한 번의 결과예요.</p>
    <table data-testid="lab-verdicts"><thead><tr><th>가정</th><th>판정</th><th>근거</th></tr></thead>
      <tbody>{rows.map(([name, v, why]) => <tr key={name}><td>{name}</td><td>{VERDICT[v]}</td><td className="small">{why}</td></tr>)}</tbody></table>
    {r.g1.verdict === "fail" && <p className="warn-text small">화면 위쪽과 렌즈를 구별할 수 없음: 이 설정에서는 렌즈 응시를 판정하지 않고 unknown으로 둬요.</p>}
    <h3>질문 패널 크기별 영역 판정</h3>
    <table data-testid="lab-panels"><thead><tr><th>높이</th><th>판정 가능</th><th>적중</th><th>unknown</th><th>다른 영역</th>
      <th>패널 밖 question 오판</th><th>패널 밖 ui 정답</th><th>패널 밖 unknown</th></tr></thead>
      <tbody>{r.panels.map((p) => <tr key={p.heightPx}><td>{p.heightPx}px</td><td>{p.resolvable ? "예" : "아니요(오차보다 작음)"}</td>
        <td>{pct(p.hit)}</td><td>{pct(p.unknown)}</td><td>{pct(p.wrong)}</td><td>{pct(p.falseQuestion)}</td><td>{pct(p.correctUi)}</td>
        <td>{pct(p.outsideUnknown)}</td></tr>)}</tbody></table>
    <h3>표본 주기</h3>
    {r.rates.some((x) => x.achievedHz !== null) ? <table data-testid="lab-rates"><thead><tr><th>목표</th><th>실제</th><th>검출 p50·p95</th>
      <th>메인 스레드 점유</th><th>지연 p95</th><th>긴 작업(10초)</th><th>유효 표본</th><th>얼굴 검출(D)</th><th>판정</th></tr></thead>
      <tbody>{r.rates.map((x) => <tr key={x.hz}><td>초당 {x.hz}회</td><td>{num(x.achievedHz, 1)}</td><td>{num(x.detectP50, 1)}·{num(x.detectP95, 1)}ms</td>
        <td>{num(x.busyPct, 1)}%</td><td>{num(x.lagP95)}ms</td><td>{x.longTasks ?? "–"}</td><td>{pct(x.valid)}</td><td>{pct(x.dDetected)}</td>
        <td>{x.achievedHz === null ? "–" : x.pass ? "통과" : "실패"}</td></tr>)}</tbody></table>
      : <p className="small muted" data-testid="lab-rates">주기 시험을 건너뛰었어요.</p>}
    {r.typing && <p className="small">글 입력 중(초당 10회): 지연 p95 {num(r.typing.lagP95)}ms · 긴 작업 {r.typing.longTasks} · 메인 스레드 점유 {num(r.typing.busyPct, 1)}%.
      CPU 사용률은 브라우저가 알려 주지 않으니 OS 작업 관리자 값을 따로 적어 주세요.</p>}
    <Diagnostics r={r} />
    <h3>실행 {runs.length}번 요약</h3>
    <p className="small">H1 통과 {passCount("g1.verdict")} · H2 통과 {passCount("g2.verdict")} · 질문 패널 {passCount("panel.verdict")} · 표본 주기 {passCount("rate.verdict")}
      (설계 기준은 새 보정 3번 중 2번 이상이며 H2 전체 통과 인증은 하지 않음)</p>
    <div className="row"><button onClick={onCopy}>집계 복사(JSON)</button><button onClick={onClear}>결과 지우기</button></div>
    {copied && <p className="small" role="status">{copied}</p>}
  </section>;
}

const DRIFT_LABEL: [keyof FeasibilityReport["diag"]["drift"], string, boolean][] = [
  ["open", "눈 뜬 정도", true], ["scale", "얼굴 크기(거리)", true], ["faceX", "얼굴 위치 가로(프레임 비율)", false],
  ["faceY", "얼굴 위치 세로(프레임 비율)", false], ["hx", "고개 좌우 특징", false], ["hy", "고개 상하 특징", false],
  ["ex", "홍채 가로(눈 폭 단위)", false], ["ey", "홍채 세로(눈 폭 단위)", false],
];

/** 판정에는 쓰지 않는 진단: 실패 원인을 가리기 위한 것(집계 복사에도 들어감, 특징점·좌표 없음) */
function Diagnostics({ r }: { r: FeasibilityReport }) {
  const signed = (v: number | null, asPct: boolean) => (v == null ? "–" : asPct ? `${v > 0 ? "+" : ""}${Math.round(v * 100)}%` : `${v > 0 ? "+" : ""}${v.toFixed(3)}`);
  return <div data-testid="lab-diag">
    <h3>진단(정확도 개선을 뜻하지 않음)</h3>
    <p className="small">관측 {r.diag.quality.total} · 유효 {r.diag.quality.accepted} · 자세·거리 변화 표시 {r.diag.quality.poseFlags}.
      자세 표시는 진단용이며 기존 거리 변화 판정 외에 모델의 거절 기준을 늘리지 않아요.</p>
    <table data-testid="lab-rejected"><thead><tr><th>거절 사유</th><th>횟수</th></tr></thead>
      <tbody>{Object.entries(r.diag.quality.rejected).map(([reason, count]) => <tr key={reason}><td>{REJECTED[reason] ?? reason}</td><td>{count}</td></tr>)}</tbody></table>
    <p className="small muted">눈 감김 후보는 기존 기준(기준 눈 뜬 정도의 절반 미만)으로 학습에서 제외하고, 검증의 unknown 분모에는 남겨요.
      화면 검증점마다 유효 표본 8개 이상이 없으면 전체 좌표 오차는 판단 보류예요. G1·G2는 실험실 전용이며 면접 평가는 하지 않아요.</p>
    <p className="small muted">렌즈 응시: 처음 보는 응시별 렌즈 확률 중앙값과 분포 밖으로 막힌 비율. 확률이 낮으면 분류기가 렌즈 응시로 보지 않은 것이고,
      분포 밖 비율이 높으면 보정 때와 자세·눈이 달라 판정을 거절한 것이에요.</p>
    <table><thead><tr><th>응시</th><th>표본</th><th>확률 중앙</th><th>분포 밖</th><th>toward</th><th>away</th><th>unknown</th></tr></thead>
      <tbody>{r.diag.lens.map((g) => <tr key={g.id}><td>{g.id}</td><td>{g.n}</td><td>{num(g.medianP, 2)}</td><td>{pct(g.oodRate)}</td>
        <td>{pct(g.toward)}</td><td>{pct(g.away)}</td><td>{pct(g.unknown)}</td></tr>)}</tbody></table>
    <p className="small">시험 앞→끝 변화(렌즈 학습 응시 → 마지막 렌즈 검증 응시, 중앙값 기준):{" "}
      {DRIFT_LABEL.map(([k, label, asPct]) => `${label} ${signed(r.diag.drift[k], asPct)}`).join(" · ")}</p>
    <table><thead><tr><th>처음 보는 위치</th><th>오차</th></tr></thead>
      <tbody>{Object.entries(r.diag.errors).map(([id, e]) => <tr key={id}><td>{id}</td><td>{num(e)}px</td></tr>)}</tbody></table>
    <p className="small muted">보정 격자 맞춤 잔차(같은 점으로 학습했으므로 정확도가 아님):{" "}
      {Object.entries(r.diag.fit).map(([id, e]) => `${id} ${num(e)}px`).join(" · ")}</p>
  </div>;
}

