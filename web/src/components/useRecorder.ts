import { useCallback, useEffect, useRef, useState } from "react";

/** 브라우저 마이크 녹음(MediaRecorder). 입력 레벨도 함께 계산해 마이크가 잡히는지 보여준다. */
export function useRecorder() {
  const [recording, setRecording] = useState(false);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startedAt = useRef(0);
  const raf = useRef(0);
  const ctxRef = useRef<AudioContext | null>(null);

  const ensureStream = useCallback(async () => {
    if (streamRef.current) return streamRef.current;
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = s;
      const ctx = new AudioContext();
      ctxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(s).connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += ((v - 128) / 128) ** 2;
        setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
        raf.current = requestAnimationFrame(tick);
      };
      tick();
      return s;
    } catch {
      setError("마이크 권한이 필요합니다. 브라우저 주소창의 권한 설정을 확인하세요.");
      throw new Error("mic");
    }
  }, []);

  const start = useCallback(async () => {
    const s = await ensureStream();
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
    const rec = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
    chunks.current = [];
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    rec.start(250);
    recRef.current = rec;
    startedAt.current = performance.now();
    setRecording(true);
  }, [ensureStream]);

  /** 녹음을 끝내고 결과(Blob, 길이 초)를 돌려준다. */
  const stop = useCallback(
    () =>
      new Promise<{ blob: Blob; durationSec: number } | null>((resolve) => {
        const rec = recRef.current;
        if (!rec || rec.state === "inactive") return resolve(null);
        rec.onstop = () => {
          const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
          setRecording(false);
          resolve({ blob, durationSec: (performance.now() - startedAt.current) / 1000 });
        };
        rec.stop();
      }),
    [],
  );

  useEffect(
    () => () => {
      cancelAnimationFrame(raf.current);
      recRef.current?.state === "recording" && recRef.current.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      ctxRef.current?.close();
    },
    [],
  );

  return { recording, level, error, start, stop, ensureStream };
}
