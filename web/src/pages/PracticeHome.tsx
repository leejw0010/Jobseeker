import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { CATEGORIES, JOB_CATEGORIES, type Application, type Category, type Question } from "../types";

const SOURCE_LABEL = { bank: "공용", generated: "맞춤", custom: "직접 추가" } as const;

export default function PracticeHome() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [questions, setQuestions] = useState<Question[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [filter, setFilter] = useState({ category: "", job_category: "", source: "", q: "" });
  const [selected, setSelected] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [essayBasis, setEssayBasis] = useState<"submitted" | "latest">("submitted");
  const [jobDescription, setJobDescription] = useState("");
  const [followups, setFollowups] = useState(true);

  // 모의시험 설정
  const [mock, setMock] = useState({ count: 5, prep_sec: 30, answer_sec: 90, job_category: "", application_id: params.get("application") ?? "" });
  const [mockCats, setMockCats] = useState<Category[]>(["인성", "직무", "기업", "상황"]);

  // 맞춤 질문 생성
  const [gen, setGen] = useState({
    application_id: params.get("application") ?? "",
    company: "",
    position: "",
    job_category: "",
    essay_text: "",
    count: 5,
  });
  const [newQ, setNewQ] = useState<{ category: Category; text: string }>({ category: "인성", text: "" });

  // 필터가 바뀌거나 reload()가 호출되면 다시 불러온다. 늦게 온 이전 응답은 버린다.
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);
  useEffect(() => {
    let alive = true;
    api.questions({ category: filter.category, job_category: filter.job_category, source: filter.source })
      .then((qs) => alive && setQuestions(qs))
      .catch((e) => setErr(e.message));
    return () => {
      alive = false;
    };
  }, [filter.category, filter.job_category, filter.source, reloadKey]);
  useEffect(() => {
    api.applications().then(setApps).catch(() => {});
  }, []);

  const shown = useMemo(
    () => (filter.q ? questions.filter((q) => q.text.includes(filter.q)) : questions),
    [questions, filter.q],
  );
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const startFree = () =>
    run(async () => {
      const s = await api.createSession({ mode: "free", question_ids: selected,
        application_id: gen.application_id || undefined, essay_basis: essayBasis,
        job_description: jobDescription, followups_enabled: followups });
      nav(`/practice/sessions/${s.id}/run`);
    });

  const startMock = () =>
    run(async () => {
      const s = await api.createSession({
        mode: "mock",
        count: mock.count,
        prep_sec: mock.prep_sec,
        answer_sec: mock.answer_sec,
        categories: mockCats,
        job_category: mock.job_category || undefined,
        application_id: mock.application_id || undefined,
        essay_basis: essayBasis,
        job_description: jobDescription,
        followups_enabled: followups,
      });
      nav(`/practice/sessions/${s.id}/run`);
    });

  const generate = () =>
    run(async () => {
      const made = await api.generateQuestions({
        application_id: gen.application_id || undefined,
        company: gen.company || undefined,
        position: gen.position || undefined,
        job_category: gen.job_category || undefined,
        essay_text: gen.essay_text || undefined,
        count: gen.count,
        essay_basis: essayBasis,
      });
      if (made.length === 0) throw new Error("새로 만든 질문이 없습니다. 같은 질문이 이미 질문은행에 있어요.");
      setFilter((f) => ({ ...f, source: "generated", category: "" }));
      setSelected(made.map((q) => q.id));
      reload();
    });

  const addCustom = () =>
    run(async () => {
      await api.addQuestion({ ...newQ, job_category: filter.job_category || null });
      setNewQ({ ...newQ, text: "" });
      reload();
    });

  return (
    <>
      <h1>면접 연습</h1>
      <p className="small muted">
        JobSeeker는 면접 연습 전용이에요. 실제 면접 중에는 쓰지 마세요. <Link to="/practice/settings">녹음·개인정보 설정</Link>
      </p>
      {err && <p className="err">{err}</p>}
      <section className="card practice-settings">
        <h2>이번 면접의 기준</h2>
        <p className="small muted">지원 건을 연결하면 시작 시점의 자소서를 보관하고, 그 내용을 기준으로 답변과 꼬리질문을 연결해요.</p>
        <div className="row">
          <label className="grow">자소서 기준
            <select value={essayBasis} onChange={(e) => setEssayBasis(e.target.value as "submitted" | "latest")}>
              <option value="submitted">제출본 우선 · 제출 표시가 없으면 최신본</option>
              <option value="latest">최신본으로 연습</option>
            </select>
          </label>
          <label className="check-label"><input type="checkbox" checked={followups} onChange={(e) => setFollowups(e.target.checked)} />답변 뒤 꼬리질문 선택하기</label>
        </div>
        <div className="spacer" />
        <label>채용 공고의 주요 업무·자격 요건 (선택)
          <textarea value={jobDescription} maxLength={12000} onChange={(e) => setJobDescription(e.target.value)} placeholder="지원하는 직무의 업무와 요구 역량을 붙여 넣어 주세요." style={{ minHeight: 80 }} />
        </label>
      </section>
      <div className="grid2">
        <section className="card">
          <h2>모의시험 모드</h2>
          <p className="small muted">실제 면접처럼 질문이 하나씩 나오고, 준비 시간 뒤 자동으로 녹음이 시작돼 제한 시간에 끝납니다.</p>
          <div className="row">
            <label>질문 수<input type="number" min={1} max={20} value={mock.count} onChange={(e) => setMock({ ...mock, count: +e.target.value })} /></label>
            <label>준비(초)<input type="number" min={0} max={300} value={mock.prep_sec} onChange={(e) => setMock({ ...mock, prep_sec: +e.target.value })} /></label>
            <label>답변(초)<input type="number" min={10} max={600} value={mock.answer_sec} onChange={(e) => setMock({ ...mock, answer_sec: +e.target.value })} /></label>
          </div>
          <div className="spacer" />
          <div className="row small">
            {CATEGORIES.map((c) => (
              <label key={c} style={{ flexDirection: "row", alignItems: "center" }}>
                <input type="checkbox" checked={mockCats.includes(c)} onChange={() => setMockCats((s) => (s.includes(c) ? s.filter((x) => x !== c) : [...s, c]))} />
                {c}
              </label>
            ))}
          </div>
          <div className="spacer" />
          <div className="row">
            <label className="grow">직무
              <select value={mock.job_category} onChange={(e) => setMock({ ...mock, job_category: e.target.value })}>
                <option value="">공통</option>
                {JOB_CATEGORIES.map((j) => <option key={j}>{j}</option>)}
              </select>
            </label>
            <label className="grow">지원 건 맞춤 질문 포함
              <select value={mock.application_id} onChange={(e) => setMock({ ...mock, application_id: e.target.value })}>
                <option value="">선택 안 함</option>
                {apps.map((a) => <option key={a.id} value={a.id}>{a.company} · {a.position}</option>)}
              </select>
            </label>
          </div>
          <div className="spacer" />
          <button className="primary" disabled={busy || mockCats.length === 0} onClick={startMock}>모의시험 시작</button>
        </section>

        <section className="card">
          <h2>맞춤 질문 만들기</h2>
          <p className="small muted">지원 건을 고르면 위에서 선택한 자소서를 바탕으로 질문을 만들어요. 직접 입력해도 됩니다.</p>
          <label>지원 건
            <select value={gen.application_id} onChange={(e) => setGen({ ...gen, application_id: e.target.value })}>
              <option value="">직접 입력</option>
              {apps.map((a) => <option key={a.id} value={a.id}>{a.company} · {a.position}</option>)}
            </select>
          </label>
          {!gen.application_id && (
            <>
              <div className="spacer" />
              <div className="row">
                <label className="grow">회사<input value={gen.company} onChange={(e) => setGen({ ...gen, company: e.target.value })} /></label>
                <label className="grow">직무<input value={gen.position} onChange={(e) => setGen({ ...gen, position: e.target.value })} /></label>
              </div>
              <div className="spacer" />
              <label>자기소개서 내용<textarea value={gen.essay_text} onChange={(e) => setGen({ ...gen, essay_text: e.target.value })} /></label>
            </>
          )}
          <div className="spacer" />
          <div className="row">
            <label>개수<input type="number" min={1} max={10} value={gen.count} onChange={(e) => setGen({ ...gen, count: +e.target.value })} /></label>
            <button className="primary" disabled={busy} onClick={generate}>질문 생성</button>
          </div>
        </section>
      </div>

      <section className="card">
        <div className="row">
          <h2 className="grow" style={{ margin: 0 }}>질문은행</h2>
          <select value={filter.category} onChange={(e) => setFilter({ ...filter, category: e.target.value })}>
            <option value="">전체 분류</option>
            {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
          <select value={filter.job_category} onChange={(e) => setFilter({ ...filter, job_category: e.target.value })}>
            <option value="">전체 직무</option>
            {JOB_CATEGORIES.map((j) => <option key={j}>{j}</option>)}
          </select>
          <select value={filter.source} onChange={(e) => setFilter({ ...filter, source: e.target.value })}>
            <option value="">전체 출처</option>
            <option value="bank">공용</option>
            <option value="generated">맞춤</option>
            <option value="custom">직접 추가</option>
          </select>
          <input placeholder="검색" value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} />
        </div>
        <div className="spacer" />
        <ul className="qlist">
          {shown.map((q) => (
            <li key={q.id}>
              <input type="checkbox" checked={selected.includes(q.id)} onChange={() => toggle(q.id)} aria-label="선택" />
              <span className="grow">{q.text}</span>
              <span className="chip">{q.category}</span>
              {q.job_category && <span className="chip">{q.job_category}</span>}
              <span className={`chip ${q.source !== "bank" ? "accent" : ""}`}>{SOURCE_LABEL[q.source]}</span>
              {q.source !== "bank" && (
                <button className="small danger" onClick={() => run(async () => { await api.deleteQuestion(q.id); reload(); })}>삭제</button>
              )}
            </li>
          ))}
          {shown.length === 0 && <li className="muted">질문이 없습니다.</li>}
        </ul>
        <div className="spacer" />
        <div className="row">
          <select value={newQ.category} onChange={(e) => setNewQ({ ...newQ, category: e.target.value as Category })}>
            {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
          <input className="grow" placeholder="질문 직접 추가" value={newQ.text} onChange={(e) => setNewQ({ ...newQ, text: e.target.value })} />
          <button disabled={busy || newQ.text.trim().length < 2} onClick={addCustom}>추가</button>
        </div>
        <div className="spacer" />
        <div className="row">
          <span className="muted small grow">{selected.length}개 선택됨</span>
          <button onClick={() => setSelected([])} disabled={!selected.length}>선택 해제</button>
          <button className="primary" disabled={busy || !selected.length} onClick={startFree}>선택한 질문으로 자유 연습</button>
        </div>
      </section>
    </>
  );
}
