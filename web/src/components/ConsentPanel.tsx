import { useEffect, useState } from "react";
import { api } from "../api";
import type { PracticeSettings } from "../types";

/** 첫 녹음 전에 받는 녹음 동의. 연습 전용 원칙과 무엇이 어디로 가는지 알리고 동의를 저장한다.
 *  원본 보관 체크는 지금 설정(initialKeepAudio)으로 시작하고, 사용자가 바꿨을 때만 함께 보낸다(다시 동의해도 설정이 풀리지 않게). */
export default function ConsentPanel({
  retentionDays = 30,
  initialKeepAudio = false,
  notice,
  buttonLabel = "동의하고 시작",
  onConsented,
}: {
  retentionDays?: number;
  initialKeepAudio?: boolean;
  notice?: string | null;
  buttonLabel?: string;
  onConsented: (s: PracticeSettings) => void;
}) {
  const [keepAudio, setKeepAudio] = useState(initialKeepAudio);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!touched) setKeepAudio(initialKeepAudio);
  }, [initialKeepAudio, touched]);

  const agree = async () => {
    setBusy(true);
    setErr(null);
    try {
      onConsented(await api.updateSettings(touched ? { consent: true, keep_audio: keepAudio } : { consent: true }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>녹음 전에 확인해 주세요</h2>
      {notice && <p className="warn-text">{notice}</p>}
      <ul className="bullets">
        <li>JobSeeker는 면접 <b>연습 전용</b>이에요. 실제 면접 중에는 쓰지 마세요. 많은 기업이 면접 중 AI 도움을 금지해요.</li>
        <li>본인 목소리만 녹음해요. 다른 사람의 목소리가 들어가지 않게 해 주세요.</li>
        <li>
          OpenAI 키가 설정된 경우 OpenAI로 보내요: 전사를 위해 <b>원본 녹음</b>을, 루브릭 채점과 세션이 끝나면 자동으로 만드는
          디브리프를 위해 <b>전사문·질문·자기평가·회고 메모·지원 회사/직무</b>를 보내요.
        </li>
        <li>기본값은 전사가 끝나면 원본 녹음을 지우고 전사문만 남겨요.</li>
        <li>원본을 남기려면 아래에 체크하세요. 남겨도 {retentionDays}일 뒤 자동으로 지워져요.</li>
        <li>AI가 만든 피드백·요약에는 ‘AI 생성’ 표시가 붙어요.</li>
      </ul>
      <label style={{ flexDirection: "row", alignItems: "center" }}>
        <input
          type="checkbox"
          checked={keepAudio}
          onChange={(e) => {
            setKeepAudio(e.target.checked);
            setTouched(true);
          }}
        />
        원본 녹음도 보관할래요
      </label>
      <div className="spacer" />
      <button className="primary" disabled={busy} onClick={agree}>{buttonLabel}</button>
      {err && <p className="err">{err}</p>}
    </section>
  );
}
