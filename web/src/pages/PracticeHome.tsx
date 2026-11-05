import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { questionsForApplication } from "../practice/questions";
import { ClassificationControls } from "../components/ClassificationControls";
import { CATEGORIES, JOB_CATEGORIES, type Application, type ApplicationDetail, type Category, type Question, type PracticeTaxonomy, type ClassificationInput } from "../types";

const SOURCE_LABEL = { bank: "공용", generated: "맞춤", custom: "직접 추가" } as const;

export default function PracticeHome() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [taxonomy,setTaxonomy]=useState<PracticeTaxonomy|null>(null);
  const [classification,setClassification]=useState<ClassificationInput>({});
  const [genClassification,setGenClassification]=useState<ClassificationInput>({});
  const [tagFilter,setTagFilter]=useState({type:'',keys:[] as string[],match:'any' as 'any'|'all'});
  const [editing,setEditing]=useState<string|null>(null);
  const [editTags,setEditTags]=useState<ClassificationInput>({});
  useEffect(()=>{api.taxonomy().then(setTaxonomy).catch(()=>{});},[]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [applicationId, setApplicationId] = useState(params.get("application") ?? "");
  const [applicationDetail, setApplicationDetail] = useState<ApplicationDetail | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setApplicationDetail(null); setPreviewError(null);
    if (applicationId) api.application(applicationId).then(a => {if(alive) setApplicationDetail(a);}).catch(e => {if(alive) setPreviewError(e.message);});
    return () => {alive=false;};
  }, [applicationId]);
  const [filter, setFilter] = useState({ category: "", job_category: "", source: "", q: "" });
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => { setSelected([]); }, [applicationId]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const [essayBasis, setEssayBasis] = useState<"submitted" | "latest">("submitted");
  const [jobDescription, setJobDescription] = useState("");
  const [followups, setFollowups] = useState(true);

  // 모의시험 설정
  const [mock, setMock] = useState({ count: 5, prep_sec: 30, answer_sec: 90, job_category: "" });
  const [mockCats, setMockCats] = useState<Category[]>(["인성", "직무", "기업", "상황"]);

  // 맞춤 질문 생성
  const [gen, setGen] = useState({
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
    api.questions({ category: filter.category, job_category: filter.job_category, source: filter.source, ...(taxonomy?.enabled?{question_type:tagFilter.type?[tagFilter.type]:[],competency_key:tagFilter.keys,competency_match:tagFilter.match}:{}) })
      .then((qs) => alive && setQuestions(qs))
      .catch((e) => setErr(e.message));
    return () => {
      alive = false;
    };
  }, [filter.category, filter.job_category, filter.source, reloadKey, taxonomy, tagFilter]);
  useEffect(() => {
    api.applications().then(setApps).catch(() => {});
  }, []);

  const shown = useMemo(
    () => questionsForApplication(questions, applicationId).filter(q => !filter.q || q.text.includes(filter.q)),
    [questions, applicationId, filter.q],
  );
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const run = async (fn: () => Promise<void>) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      running.current = false;
      setBusy(false);
    }
  };

  const startFree = () =>
    run(async () => {
      const s = await api.createSession({ mode: "free", question_ids: selected,
        application_id: applicationId || undefined, essay_basis: essayBasis,
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
        application_id: applicationId || undefined,
        essay_basis: essayBasis,
        job_description: jobDescription,
        followups_enabled: followups,
        ...(taxonomy?.enabled?{question_types:tagFilter.type?[tagFilter.type]:[],competency_keys:tagFilter.keys,competency_match:tagFilter.match}:{}),
      });
      nav(`/practice/sessions/${s.id}/run`);
    });

  const generate = () =>
    run(async () => {
      const made = await api.generateQuestions({
        application_id: applicationId || undefined,
        ...(!applicationId ? {
          company: gen.company || undefined,
          position: gen.position || undefined,
          job_category: gen.job_category || undefined,
          essay_text: gen.essay_text || undefined,
        } : {}),
        count: gen.count,
        essay_basis: essayBasis,
        ...(taxonomy?.enabled?genClassification:{}),
      });
      if (made.length === 0) throw new Error("새로 만든 질문이 없습니다. 같은 질문이 이미 질문은행에 있어요.");
      setFilter((f) => ({ ...f, source: "generated", category: "" }));
      setSelected(made.map((q) => q.id));
      reload();
    });

  const addCustom = () =>
    run(async () => {
      await api.addQuestion({ ...newQ, job_category: filter.job_category || null, ...(taxonomy?.enabled?classification:{}) });
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
        <label>이번 연습에 연결할 지원 건
          <select value={applicationId} disabled={busy} onChange={e => setApplicationId(e.target.value)}>
            <option value="">연결 안 함 · 직접 입력으로 질문 생성 가능</option>
            {apps.map(a => <option key={a.id} value={a.id}>{a.company} · {a.position}</option>)}
          </select>
        </label>
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
        <div data-testid="practice-context-preview" className="small">
          <h3>시작 전 기준 자료 확인</h3>
          <p>{applicationId ? applicationDetail ? `${applicationDetail.company} · ${applicationDetail.position}` : previewError ?? "지원 건을 불러오는 중…" : "연결된 지원 건 없음 · 제출본 연결은 판단유보로 안내해요."}</p>
          <p>자소서: {essayBasis === "submitted" ? "제출본 우선 · 없으면 최신본" : "최신본"} · 공고 {jobDescription.trim() ? "포함" : "없음"} · 꼬리질문 {followups ? "사용" : "사용 안 함"}</p>
          {applicationDetail?.essay_items.map(item => {
            const submitted=item.versions.find(v=>v.id===item.submitted_version_id);
            const version=essayBasis==='submitted'&&submitted ? submitted : item.versions[item.versions.length-1];
            return version ? <p key={item.id}>{item.question_text} · v{version.version_no} · {essayBasis==='submitted'&&submitted ? item.submission_confirmation==='confirmed' ? '제출본 · 확인됨' : item.submission_confirmation==='legacy_unverified' ? '이전 제출 표시 · 확인 전' : '제출본 · 확인 기록 없음' : '최신본'}</p> : null;
          })}
          <p className="muted">자유 연습과 모의시험 모두 이 기준을 사용해요. 실제 기준 자료는 시작하는 순간 고정해요.</p>
        </div>
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
            <p className="small muted">위에서 연결한 지원 건의 맞춤 질문을 포함해요.</p>
          </div>
          <div className="spacer" />
          {taxonomy?.enabled&&<p className="small muted">아래 질문은행의 질문 유형·역량 필터가 모의시험 질문 선택에도 적용돼요.</p>}
          <button className="primary" disabled={busy || mockCats.length === 0} onClick={startMock}>모의시험 시작</button>
        </section>

        <section className="card">
          <h2>맞춤 질문 만들기</h2>
          <p className="small muted">지원 건을 고르면 위에서 선택한 자소서를 바탕으로 질문을 만들어요. 직접 입력해도 됩니다.</p>
          <p className="small muted">위에서 연결한 지원 건을 질문 생성에도 사용해요. 아래 직접 입력은 질문을 만들 때만 쓰며 세션 기준 자료로 저장되지 않아요.</p>
          {!applicationId && (
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
          <ClassificationControls taxonomy={taxonomy} value={genClassification} onChange={setGenClassification} label="생성할 질문 분류"/>
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
        <p className="small muted">지원 건을 바꾸면 질문을 다시 선택해 주세요. 지원 건을 연결하면 해당 지원 건과 공통 질문만 보여요.</p>
        {taxonomy?.enabled&&<fieldset><legend>질문 유형·역량 필터</legend><label>질문 유형 필터<select value={tagFilter.type} onChange={e=>setTagFilter({...tagFilter,type:e.target.value})}><option value="">전체 유형</option>{taxonomy.question_types.map(t=><option key={t.key} value={t.key}>{t.label}</option>)}</select></label><div className="row small">{taxonomy.competencies.map(c=><label className="check-label" key={c.key}><input type="checkbox" checked={tagFilter.keys.includes(c.key)} onChange={()=>setTagFilter({...tagFilter,keys:tagFilter.keys.includes(c.key)?tagFilter.keys.filter(k=>k!==c.key):[...tagFilter.keys,c.key]})}/>{c.label}</label>)}</div><label>역량 필터 조건<select value={tagFilter.match} onChange={e=>setTagFilter({...tagFilter,match:e.target.value as 'any'|'all'})}><option value="any">하나 이상 포함</option><option value="all">모두 포함</option></select></label></fieldset>}
        <ul className="qlist">
          {shown.map((q) => (
            <li key={q.id} style={{flexWrap:"wrap"}}>
              <input type="checkbox" checked={selected.includes(q.id)} onChange={() => toggle(q.id)} aria-label={`질문 선택: ${q.text}`} />
              <span className="grow">{q.text}</span>
              <span className="chip">{q.category}</span>
              {q.job_category && <span className="chip">{q.job_category}</span>}
              <span className={`chip ${q.source !== "bank" ? "accent" : ""}`}>{SOURCE_LABEL[q.source]}</span>
              {taxonomy?.enabled&&<><span className="chip">{taxonomy.question_types.find(t=>t.key===q.question_type)?.label??'유형 미분류'}</span>{q.competency_keys?.map(k=><span className="chip" key={k}>{taxonomy.competencies.find(c=>c.key===k)?.label??k}</span>)}</>}
              {taxonomy?.enabled&&q.source!=="bank"&&<button className="small" onClick={()=>{setEditing(editing===q.id?null:q.id);setEditTags({question_type:q.question_type,competency_keys:q.competency_keys??[]});}}>분류 편집</button>}
              {editing===q.id&&<div style={{flexBasis:'100%'}}><ClassificationControls taxonomy={taxonomy} value={editTags} onChange={setEditTags} label="질문 분류 편집"/><p className="small muted">기존 세션의 시작 시점 분류는 바뀌지 않아요.</p><button disabled={busy} onClick={()=>run(async()=>{await api.classifyQuestion(q.id,editTags);setEditing(null);reload();})}>분류 저장</button><button onClick={()=>setEditing(null)}>취소</button></div>}
              {q.source !== "bank" && (
                <button className="small danger" disabled={busy} onClick={() => run(async () => { await api.deleteQuestion(q.id); reload(); })}>삭제</button>
              )}
            </li>
          ))}
          {shown.length === 0 && <li className="muted">질문이 없습니다.</li>}
        </ul>
        <div className="spacer" />
        <ClassificationControls taxonomy={taxonomy} value={classification} onChange={setClassification} label="직접 추가할 질문 분류"/>
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
