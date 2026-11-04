import { useCallback, useEffect, useRef, useState } from "react";
import { CAMERA_DEBUG, emptyCounts, type CameraDiag } from "../video/debug";
import { loadFaceDetector, type FaceDetector } from "../video/detector";
import { createDGrid, createRateStats, type Frame, type RateSnapshot } from "../video/gaze/sampler";
import { SAMPLE_MS, createFaceSampler, edgeLabel, faceFeatures, summarizeSegment, type FaceSample, type FaceState, type Overshoot } from "../video/metrics";

export type CameraStatus = "off" | "starting" | "on" | "error";

/** 기본 표본 주기(초당 횟수). D 지표만 쓸 때의 주기(SAMPLE_MS)와 같다 */
const DEFAULT_HZ = 1000 / SAMPLE_MS;

/** 선택 기능인 카메라 자세 분석. 마이크(useRecorder)와 별도 스트림을 쓰고, 프레임은 브라우저 안에서만 검출한다.
 *  beginSegment~endSegment 사이(답변하는 동안)의 표본만 요약해 돌려준다. 끄거나 화면을 떠나면 카메라를 바로 놓는다.
 *  시선 분석(G)은 같은 스트림·같은 검출 결과를 subscribeFrames로 받아 쓰고, 필요하면 setTargetHz로 주기를 올린다. */
export function useFaceAnalysis() {
  const [status, setStatus] = useState<CameraStatus>("off");
  const [error, setError] = useState<string | null>(null);
  const [face, setFace] = useState<FaceState | null>(null);
  // edge일 때 넘은 쪽(실시간 안내용). 안내 문구가 바뀔 때만 갱신한다
  const [edge, setEdge] = useState<Overshoot | null>(null);
  const lastEdge = useRef("");
  // 개발 전용 진단(CAMERA_DEBUG). 끄면 갱신하지 않는다
  const [diag, setDiag] = useState<CameraDiag | null>(null);
  const counts = useRef(emptyCounts());
  const video = useRef<HTMLVideoElement | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const detector = useRef<FaceDetector | null>(null);
  const preparingDetector = useRef<FaceDetector | null>(null);
  const timer = useRef(0);
  const lastFace = useRef<FaceState | null>(null);
  const segment = useRef<ReturnType<typeof createFaceSampler> | null>(null);
  const segStart = useRef(0);
  // 켜는 중에 끄거나 화면을 떠나면 늦게 도착한 카메라·검출기를 바로 정리한다
  const gen = useRef(0);
  // 표본 주기와 예정 시각. 주기가 바뀔 수 있어 setInterval 대신 setTimeout을 이어 건다
  const hz = useRef(DEFAULT_HZ);
  const due = useRef(0);
  const loop = useRef<() => void>(() => {});
  const subscribers = useRef(new Set<(f: Frame) => void>());
  const grid = useRef(createDGrid());
  const stats = useRef(createRateStats());
  const longTasks = useRef<PerformanceObserver | null>(null);

  const release = useCallback(() => {
    gen.current++;
    clearTimeout(timer.current);
    longTasks.current?.disconnect();
    longTasks.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    detector.current?.close();
    detector.current = null;
    preparingDetector.current?.close();
    preparingDetector.current = null;
    if (video.current) video.current.srcObject = null;
    lastFace.current = null;
    setFace(null);
    lastEdge.current = "";
    setEdge(null);
    counts.current = emptyCounts();
    setDiag(null);
  }, []);

  const fail = useCallback((message: string) => {
    release();
    setStatus("error");
    setError(message);
  }, [release]);

  const tick = useCallback((lagMs: number) => {
    const v = video.current, d = detector.current;
    if (!v || !d || document.hidden || v.readyState < 2 || !v.videoWidth) return;
    const result = (() => {
      try {
        const t = performance.now();
        const points = d.detect(v, t);
        return { t, points, detectMs: performance.now() - t, sample: { t, ...faceFeatures(points) } as FaceSample };
      } catch {
        return null;
      }
    })();
    if (!result) {
      fail("영상 분석이 멈췄어요. 지금까지 잰 값은 남기고 카메라를 껐어요. 면접 연습은 그대로 이어 갈 수 있어요.");
      return;
    }
    const { t, points, detectMs, sample } = result;
    stats.current.add({ t, detectMs, lagMs });
    const frame: Frame = { t, points, width: v.videoWidth, height: v.videoHeight, detectMs };
    subscribers.current.forEach((cb) => {
      try { cb(frame); } catch { /* 구독자 오류가 검출 반복과 D 지표를 멈추지 않게 한다 */ }
    });
    // D 요약은 지금처럼 초당 약 4회만 받는다. 기본 주기에서는 모든 표본을 넣는다(격자를 쓰면 타이머 오차로 표본을 놓칠 수 있다)
    const forD = hz.current <= DEFAULT_HZ || grid.current.accept(t);
    if (forD) segment.current?.add(sample);
    if (sample.state !== lastFace.current) { lastFace.current = sample.state; setFace(sample.state); }
    const edgeKey = sample.overshoot ? edgeLabel(sample.overshoot) : "";
    if (edgeKey !== lastEdge.current) { lastEdge.current = edgeKey; setEdge(sample.overshoot ?? null); }
    if (CAMERA_DEBUG && forD) {
      const c = counts.current;
      c[sample.state]++;
      if (sample.state === "edge" && sample.coreInside) c.edgeCore++;
      setDiag({ sample, width: v.videoWidth, height: v.videoHeight, counts: { ...c } });
    }
  }, [fail]);

  // 매 렌더에서 최신 tick을 쓰도록 반복 함수를 ref에 둔다
  loop.current = () => {
    if (!detector.current) return;
    const period = 1000 / hz.current;
    tick(Math.max(0, performance.now() - due.current));
    if (!detector.current) return; // 검출이 멈춰 카메라를 껐다
    // 예정 시각을 지키되, 탭이 가려졌다 돌아와 한참 늦었으면 몰아서 돌지 않고 반 주기 뒤부터 다시 센다
    due.current = Math.max(due.current + period, performance.now() + period / 2);
    timer.current = window.setTimeout(() => loop.current(), Math.max(0, due.current - performance.now()));
  };

  const schedule = useCallback(() => {
    clearTimeout(timer.current);
    const period = 1000 / hz.current;
    due.current = performance.now() + period;
    timer.current = window.setTimeout(() => loop.current(), period);
  }, []);

  const enable = useCallback(async () => {
    release();
    const my = gen.current;
    setStatus("starting");
    setError(null);
    const [s, d] = await Promise.all([
      // HTTP 주소 등에서는 mediaDevices가 없다. 그때도 거부와 같이 처리한다
      Promise.resolve().then(() => navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, audio: false })).then((s) => {
        // 검출기 준비와 별개로 도착 즉시 소유한다. 준비 중 떠나도 release가 이 스트림을 닫아야 한다.
        if (my !== gen.current) { s.getTracks().forEach((t) => t.stop()); return null; }
        stream.current = s;
        return s;
      }, () => {
        if (my === gen.current) fail("카메라를 사용할 수 없어요. 브라우저의 카메라 권한이나 다른 앱의 사용 여부를 확인해 주세요. 카메라 없이도 면접 연습은 그대로 할 수 있어요.");
        return null;
      }),
      loadFaceDetector().then((d) => {
        if (my !== gen.current) { d.close(); return null; }
        preparingDetector.current = d;
        return d;
      }, () => {
        // 다른 자원이 아직 권한 응답을 기다려도 실패를 즉시 알리고, 늦게 온 자원은 위 세대 검사로 정리한다.
        if (my === gen.current) fail("영상 분석 모델을 불러오지 못해 카메라를 껐어요. 카메라 없이도 면접 연습은 그대로 할 수 있어요.");
        return null;
      }),
    ]);
    if (my !== gen.current || !s || !d) return;
    preparingDetector.current = null;
    detector.current = d;
    stats.current = createRateStats();
    grid.current = createDGrid();
    try {
      // 메인 스레드를 50ms 넘게 막은 작업(브라우저가 지원할 때만). 표본 주기가 화면 응답성을 해치는지 보는 데 쓴다
      const po = new PerformanceObserver((list) => {
        for (const e of list.getEntries()) stats.current.add({ t: e.startTime, detectMs: 0, lagMs: 0, longTask: true });
      });
      po.observe({ type: "longtask", buffered: false });
      longTasks.current = po;
    } catch { /* 지원하지 않는 브라우저 */ }
    s.getVideoTracks().forEach((t) => { t.onended = () => fail("카메라 연결이 끊겼어요. 지금까지 잰 값은 남겨 두었어요."); });
    if (video.current) { video.current.srcObject = s; video.current.play().catch(() => {}); }
    schedule();
    setStatus("on");
  }, [fail, release, schedule]);

  const disable = useCallback(() => {
    release();
    setStatus("off");
    setError(null);
  }, [release]);

  /** 미리보기 <video>에 붙이는 ref. 카메라가 이미 켜져 있으면 바로 연결한다 */
  const attachVideo = useCallback((el: HTMLVideoElement | null) => {
    video.current = el;
    if (el && stream.current && el.srcObject !== stream.current) { el.srcObject = stream.current; el.play().catch(() => {}); }
  }, []);

  /** 답변을 시작할 때 부른다. 카메라가 꺼져 있으면 아무것도 재지 않는다 */
  const beginSegment = useCallback(() => {
    segment.current = detector.current ? createFaceSampler() : null;
    segStart.current = performance.now();
    counts.current = emptyCounts();
  }, []);
  /** 답변을 마칠 때 부른다. 시작할 때 카메라가 켜져 있었으면 표본이 없어도(카메라 화면 준비 전, 도중에 끔) 요약을 돌려준다:
   *  답변 시간과 분석한 시간의 차이가 분석하지 못한 시간이다. 시작할 때 꺼져 있었으면 null */
  const endSegment = useCallback(() => {
    const samples = segment.current;
    segment.current = null;
    return samples ? summarizeSegment(samples.snapshot(), { start: segStart.current, end: performance.now() }) : null;
  }, []);

  /** 검출 결과를 프레임마다 받는다(시선 분석용). 돌려준 함수를 부르면 그만 받는다. 특징점은 메모리에서만 쓴다 */
  const subscribeFrames = useCallback((cb: (f: Frame) => void) => {
    subscribers.current.add(cb);
    return () => { subscribers.current.delete(cb); };
  }, []);
  /** 표본 주기(초당 횟수)를 바꾼다. 기본 4. 높이면 D에는 250ms 격자의 표본만 들어가 D 요약은 그대로다 */
  const setTargetHz = useCallback((h: number) => {
    hz.current = h;
    stats.current = createRateStats(); // 통계는 새 주기의 것만 남긴다
    if (detector.current) schedule();
  }, [schedule]);
  /** 최근 10초의 실제 주기·검출 시간·지연·긴 작업 통계 */
  const rateSnapshot = useCallback((): RateSnapshot => stats.current.snapshot(hz.current), []);

  useEffect(() => release, [release]);

  return { status, error, face, edge, diag, enable, disable, attachVideo, beginSegment, endSegment, subscribeFrames, setTargetHz, rateSnapshot };
}
