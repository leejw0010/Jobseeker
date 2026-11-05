import { useCallback, useEffect, useRef, useState } from "react";
import { byteTimeDomainEnergy, createVoiceSampler, summarizeVoice, type DeliverySummary } from "../delivery/voice";

/** 브라우저 마이크 녹음(MediaRecorder). 입력 레벨도 함께 계산해 마이크가 잡히는지 보여준다.
 *  권한 요청은 한 번에 하나만 보낸다. 권한 응답이 화면을 떠난 뒤에 오면 그 스트림을 바로 닫는다. */
export function useRecorder() {
  const [recording, setRecording] = useState(false);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const pending = useRef<Promise<MediaStream> | null>(null);
  const mounted = useRef(true);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startedAt = useRef(0);
  const raf = useRef(0);
  const ctxRef = useRef<AudioContext | null>(null);
  const voice = useRef<ReturnType<typeof createVoiceSampler> | null>(null);

  const open = useCallback(async (): Promise<MediaStream> => {
    let s: MediaStream;
    try {
      s = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      if (mounted.current) setError("마이크 권한이 필요합니다. 브라우저 주소창의 권한 설정을 확인하세요.");
      throw new Error("mic");
    }
    if (!mounted.current) {
      // 권한을 묻는 동안 화면을 떠났다: 정리는 이미 끝났으므로 늦게 온 스트림을 여기서 닫는다
      s.getTracks().forEach((t) => t.stop());
      throw new Error("unmounted");
    }
    streamRef.current = s;
    // AudioContext is an optional meter. Unsupported/blocked analysis must never block MediaRecorder.
    try {
      const ctx = new AudioContext();
      ctxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(s).connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const tick = () => {
        try {
          analyser.getByteTimeDomainData(buf);
          const {rms,clipped} = byteTimeDomainEnergy(buf);
          setLevel(Math.min(1, rms * 4));
          voice.current?.add({ t: (performance.now() - startedAt.current) / 1000, rms, clipped });
          raf.current = requestAnimationFrame(tick);
        } catch {
          setLevel(0); // Analyser failure leaves a visible coverage gap; recording continues.
        }
      };
      tick();
    } catch {
      void ctxRef.current?.close().catch(() => {});
      ctxRef.current = null;
      setLevel(0);
    }
    return s;
  }, []);

  const ensureStream = useCallback((): Promise<MediaStream> => {
    if (streamRef.current) return Promise.resolve(streamRef.current);
    // 권한을 묻는 중에 또 부르면(버튼을 두 번 누름 등) 같은 요청을 기다린다
    pending.current ??= open().finally(() => { pending.current = null; });
    return pending.current;
  }, [open]);

  const start = useCallback(async () => {
    const s = await ensureStream();
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
    const rec = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
    chunks.current = [];
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    rec.start(250);
    recRef.current = rec;
    startedAt.current = performance.now();
    voice.current = createVoiceSampler();
    setRecording(true);
  }, [ensureStream]);

  /** 녹음을 끝내고 결과(Blob, 길이 초)를 돌려준다. */
  const stop = useCallback(
    () =>
      new Promise<{ blob: Blob; durationSec: number; delivery?: DeliverySummary } | null>((resolve) => {
        const rec = recRef.current;
        if (!rec || rec.state === "inactive") return resolve(null);
        rec.onstop = () => {
          const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
          setRecording(false);
          const durationSec = (performance.now() - startedAt.current) / 1000;
          let delivery: DeliverySummary | undefined;
          try { delivery = summarizeVoice(voice.current?.snapshot() ?? [], durationSec); } catch { /* optional */ }
          voice.current = null;
          resolve({ blob, durationSec, delivery });
        };
        rec.stop();
      }),
    [],
  );

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      cancelAnimationFrame(raf.current);
      if (recRef.current?.state === "recording") recRef.current.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      void ctxRef.current?.close().catch(() => {});
      voice.current = null;
      recRef.current = streamRef.current = ctxRef.current = null;
    };
  }, []);

  return { recording, level, error, start, stop, ensureStream };
}
