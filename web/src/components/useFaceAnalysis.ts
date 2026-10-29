import { useCallback, useEffect, useRef, useState } from "react";
import { loadFaceDetector, type FaceDetector } from "../video/detector";
import { SAMPLE_MS, faceFeatures, summarizeSegment, type FaceSample, type FaceState } from "../video/metrics";

export type CameraStatus = "off" | "starting" | "on" | "error";

/** 선택 기능인 카메라 자세 분석. 마이크(useRecorder)와 별도 스트림을 쓰고, 프레임은 브라우저 안에서만 검출한다.
 *  beginSegment~endSegment 사이(답변하는 동안)의 표본만 요약해 돌려준다. 끄거나 화면을 떠나면 카메라를 바로 놓는다. */
export function useFaceAnalysis() {
  const [status, setStatus] = useState<CameraStatus>("off");
  const [error, setError] = useState<string | null>(null);
  const [face, setFace] = useState<FaceState | null>(null);
  const video = useRef<HTMLVideoElement | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const detector = useRef<FaceDetector | null>(null);
  const timer = useRef(0);
  const lastFace = useRef<FaceState | null>(null);
  const segment = useRef<FaceSample[] | null>(null);
  // 켜는 중에 끄거나 화면을 떠나면 늦게 도착한 카메라·검출기를 바로 정리한다
  const gen = useRef(0);

  const release = useCallback(() => {
    gen.current++;
    clearInterval(timer.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    detector.current?.close();
    detector.current = null;
    if (video.current) video.current.srcObject = null;
    lastFace.current = null;
    setFace(null);
  }, []);

  const fail = useCallback((message: string) => {
    release();
    setStatus("error");
    setError(message);
  }, [release]);

  const tick = useCallback(() => {
    const v = video.current, d = detector.current;
    if (!v || !d || document.hidden || v.readyState < 2 || !v.videoWidth) return;
    let sample: FaceSample;
    try {
      const t = performance.now();
      sample = { t, ...faceFeatures(d.detect(v, t)) };
    } catch {
      fail("영상 분석이 멈췄어요. 지금까지 잰 값은 남기고 카메라를 껐어요. 면접 연습은 그대로 이어 갈 수 있어요.");
      return;
    }
    segment.current?.push(sample);
    if (sample.state !== lastFace.current) { lastFace.current = sample.state; setFace(sample.state); }
  }, [fail]);

  const enable = useCallback(async () => {
    release();
    const my = gen.current;
    setStatus("starting");
    setError(null);
    const [cam, det] = await Promise.allSettled([
      // HTTP 주소 등에서는 mediaDevices가 없다. 그때도 거부와 같이 처리한다
      Promise.resolve().then(() => navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, audio: false })),
      loadFaceDetector(),
    ]);
    const s = cam.status === "fulfilled" ? cam.value : null, d = det.status === "fulfilled" ? det.value : null;
    if (my !== gen.current || !s || !d) {
      s?.getTracks().forEach((t) => t.stop());
      d?.close();
      if (my !== gen.current) return;
      setStatus("error");
      setError(!s
        ? "카메라를 사용할 수 없어요. 브라우저의 카메라 권한이나 다른 앱의 사용 여부를 확인해 주세요. 카메라 없이도 면접 연습은 그대로 할 수 있어요."
        : "영상 분석 모델을 불러오지 못해 카메라를 껐어요. 카메라 없이도 면접 연습은 그대로 할 수 있어요.");
      return;
    }
    stream.current = s;
    detector.current = d;
    s.getVideoTracks().forEach((t) => { t.onended = () => fail("카메라 연결이 끊겼어요. 지금까지 잰 값은 남겨 두었어요."); });
    if (video.current) { video.current.srcObject = s; video.current.play().catch(() => {}); }
    timer.current = window.setInterval(tick, SAMPLE_MS);
    setStatus("on");
  }, [fail, release, tick]);

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
  const beginSegment = useCallback(() => { segment.current = detector.current ? [] : null; }, []);
  /** 답변을 마칠 때 부른다. 잰 표본이 없으면 null */
  const endSegment = useCallback(() => {
    const samples = segment.current;
    segment.current = null;
    return samples?.length ? summarizeSegment(samples) : null;
  }, []);

  useEffect(() => release, [release]);

  return { status, error, face, enable, disable, attachVideo, beginSegment, endSegment };
}
