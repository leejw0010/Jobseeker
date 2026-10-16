import { useEffect, useState } from "react";
import { api } from "../api";
import ConsentPanel from "../components/ConsentPanel";
import type { DeleteResult, PracticeSettings as Settings } from "../types";

/** 삭제 결과 문구. 저장소 오류로 못 지운 녹음이 있으면 그 수와 자동 재시도(서버의 만료 정리)를 알린다. */
function deleteMessage({ deleted, failed }: DeleteResult, none: string) {
  const done = deleted > 0 ? `원본 녹음 ${deleted}개를 지웠어요.` : failed > 0 ? "" : none;
  const left = failed > 0 ? `${deleted > 0 ? "나머지" : "원본 녹음"} ${failed}개는 아직 지우지 못했어요. 잠시 뒤 자동으로 다시 지워요.` : "";
  return { text: [done, left].filter(Boolean).join(" "), warn: failed > 0 };
}

/** 녹음 동의·원본 보관·삭제를 관리하는 화면 */
export default function PracticeSettings() {
  const [st, setSt] = useState<Settings | null>(null);
  const [openai, setOpenai] = useState<boolean | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; warn: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.settings().then(setSt).catch((e) => setErr(e.message));
    api.health().then((h) => setOpenai(h.openai)).catch(() => {});
  }, []);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const toggleKeep = (keep_audio: boolean) => run(async () => setSt(await api.updateSettings({ keep_audio })));

  const deleteAll = () => {
    if (!confirm("원본 녹음을 모두 지울까요? 전사문과 연습 기록은 남아요. 전사문이 없는 답변은 내용이 남지 않아요. 되돌릴 수 없어요.")) return;
    run(async () => setMsg(deleteMessage(await api.deleteAllRecordings(), "지울 원본 녹음이 없어요.")));
  };

  const withdraw = () => {
    if (!confirm("동의를 철회하면 지금까지의 원본 녹음이 모두 지워지고, 다시 동의할 때까지 새 녹음을 할 수 없어요. 전사문과 연습 기록은 남지만, 전사문이 없는 답변은 내용이 남지 않아요. 철회할까요?")) return;
    run(async () => {
      const r = await api.updateSettings({ consent: false });
      setSt(r);
      const m = deleteMessage(r, "지울 원본 녹음은 없었어요.");
      setMsg({ ...m, text: `동의를 철회했어요. ${m.text}` });
    });
  };

  if (err && !st) return <p className="err">{err}</p>;
  if (!st) return <p className="muted">불러오는 중…</p>;
  const days = st.retention_days;

  return (
    <>
      <h1>녹음·개인정보</h1>
      {msg && <p className={msg.warn ? "warn-text" : "ok-text"}>{msg.text}</p>}
      {err && <p className="err">{err}</p>}

      <section className="card">
        <h2>연습 전용</h2>
        <p className="small" style={{ margin: 0 }}>
          JobSeeker는 면접 <b>연습 전용</b>이에요. 실제 면접 중에는 쓰지 마세요. 많은 기업이 면접 중 AI 도움을 금지해요.
        </p>
      </section>

      {st.consented_at ? (
        <section className="card">
          <div className="row">
            <h2 className="grow" style={{ margin: 0 }}>녹음 동의</h2>
            <span className="chip good">동의함</span>
          </div>
          <p className="small">{new Date(st.consented_at).toLocaleDateString("ko-KR")}에 동의했어요.</p>
          <button className="danger" disabled={busy} onClick={withdraw}>동의 철회</button>
          <p className="small muted" style={{ marginBottom: 0 }}>
            철회하면 원본 녹음은 모두 지워지고 새 녹음은 막혀요. 전사문과 연습 기록은 남아요.
          </p>
        </section>
      ) : (
        <ConsentPanel
          retentionDays={days}
          initialKeepAudio={st.keep_audio}
          buttonLabel="동의하기"
          onConsented={(s) => {
            setSt(s);
            setMsg({ text: "녹음에 동의했어요.", warn: false });
          }}
        />
      )}

      <section className="card">
        <h2>원본 녹음 보관</h2>
        {/* 보관 체크는 한 곳에만: 동의 전에는 위 동의 패널에서 고른다 */}
        {st.consented_at ? (
          <>
            <label style={{ flexDirection: "row", alignItems: "center" }}>
              <input type="checkbox" checked={st.keep_audio} disabled={busy} onChange={(e) => toggleKeep(e.target.checked)} />
              원본 녹음도 보관할래요
            </label>
            <p className="small muted">바꾸면 새 녹음부터 적용돼요. 이미 저장된 녹음은 원래 삭제 예정일을 따라요.</p>
          </>
        ) : (
          <p className="small muted">원본 보관 여부는 위 동의 패널에서 골라요.</p>
        )}
        <ul className="bullets small">
          <li>기본값: 전사가 끝나면 원본 녹음을 바로 지우고 전사문만 남겨요.</li>
          <li>보관을 켜도 원본은 {days}일 뒤 자동으로 지워져요.</li>
          <li>전사에 실패한 녹음은 다시 시도할 수 있게 남겨 두지만, 이것도 {days}일 뒤 지워져요.</li>
        </ul>
        <button className="danger" disabled={busy} onClick={deleteAll}>내 원본 녹음 모두 지우기</button>
      </section>

      <section className="card">
        <h2>무엇을 어디로 보내나요</h2>
        {openai === false && <p className="small muted">지금은 OpenAI 키가 없어 OpenAI로 보내는 것은 없어요.</p>}
        <ul className="bullets small">
          <li><b>원본 녹음</b> → JobSeeker 저장소. 전사 직후 지우고, 보관을 켰다면 최대 {days}일 동안 남아요.</li>
          <li><b>원본 녹음</b> → OpenAI 음성 전사(키가 설정된 경우).</li>
          <li>
            <b>전사문·질문·자기평가·회고 메모·지원 회사/직무</b> → OpenAI 루브릭 채점·세션 디브리프(키가 설정된 경우).
            디브리프는 세션이 끝나면 자동으로 만들어요.
          </li>
          <li><b>전사문·자기평가·회고 메모</b> → JobSeeker 데이터베이스. 연습 기록을 지울 때까지 남아요.</li>
          <li>목소리·표정·감정은 분석하지 않아요. 말한 내용만 봐요.</li>
        </ul>
      </section>
    </>
  );
}
