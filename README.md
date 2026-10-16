# JobSeeker: ② Practice · ③ Track

캡스톤 설계(26-2) JobSeeker 중 **② AI 인적성·면접 연습**과 **③ 지원 이력·버전 관리** 부분입니다.
발표자료의 스택(React+TS, FastAPI, Supabase, OpenAI)을 그대로 따랐습니다.

```
jobseeker/
├─ supabase/             Supabase에 붙여 넣을 테이블·RLS·Storage 버킷(schema.sql)과 마이그레이션
├─ backend/              FastAPI (Practice·Track API, 테스트 68개)
├─ web/                  React + TypeScript (Vite) 웹 화면
├─ extension-track/      크롬 확장 팝업 (공고 저장, 최근 지원 현황, 대시보드 열기)
└─ docs/screenshots/     실제 실행 화면
```

## 구현한 기능

| 발표자료 항목 | 구현 내용 |
|---|---|
| ② Question Bank & Tailored Questions | 공용 질문은행 30문항(인성·직무·기업·상황·인적성, 직무별), 직접 추가, 지원 건(회사·직무·최신 자소서)으로 맞춤 꼬리질문 생성, 같은 질문 중복 저장 방지 |
| ② Mock Test Mode | 질문 수·준비 시간·답변 제한 시간 설정. 자기소개로 시작하고, 준비 시간이 끝나면 자동 녹음, 제한 시간이 되면 자동 종료 |
| ② Recording & Transcription | 브라우저 MediaRecorder 녹음(마이크 입력 레벨 표시), Supabase Storage(또는 로컬) 저장, OpenAI STT 전사, 실패 시 재시도 |
| ② Review & Reflection | 녹음 다시 듣기(보관을 고른 경우), 전사문 수정, 별점 자기평가, 회고 메모, 전사문 인용형 STAR 루브릭 피드백, 세션 종료 자동 디브리프, 약점 질문 다시 연습, 분당 발화 글자 수, 연습 기록 목록 |
| ③ Application Records & Stage Outcomes | 지원 건 CRUD, 서류→인적성→1차→2차→최종 단계별 결과 기록(합격 시 다음 단계로 자동 진행) |
| ③ Answer Version Management | 자소서 문항별 버전 이력, 제출본 표시, 단어 단위 비교(diff), 예전 버전으로 되돌리기, 글자 수 제한 표시, 예전 답변 검색 |
| ③ Extension & Web Synchronization | `POST /track/sync`: 크롬 확장(①)이 제출한 지원서를 URL 기준으로 저장하고, 내용이 바뀐 문항만 새 버전으로 쌓음 |
| ③ Statistics by Job Category & Stage | 단계별 도달·통과·탈락·대기, 직무 분류별 단계 통과율, 월별 지원 수 |

## 연습 전용 원칙과 P0 기능

경쟁 서비스 Final Round AI 분석 보고서(프로젝트 공유 폴더 `research/reports/Final Round AI 경쟁 분석.md`)의 로드맵 P0 세 가지입니다.

- **연습 전용, 녹음 개인정보 기본값.** 실제 면접 중에 답을 띄우는 기능은 만들지 않습니다(Google·Amazon·Anthropic 등이 면접 중 AI 도움을 금지). 첫 녹음 전에 동의를 받고(서버에서도 막음), 전사가 끝나면 원본 녹음을 바로 지우고 전사문만 남깁니다. 원본 보관은 사용자가 고를 때만 하고, 보관해도 `AUDIO_RETENTION_DAYS`(기본 30일) 뒤 자동 삭제합니다. `/practice/settings` 화면에서 보관 설정, 원본 모두 지우기, 동의 철회를 할 수 있고, OpenAI로 무엇이 가는지 적어 두었습니다. AI가 만든 피드백·요약에는 'AI 생성' 표시가 붙습니다(AI 기본법 제31조 고지 의무 대비).
- **전사문 인용형 STAR 루브릭 피드백.** 상황·과제 / 본인 행동 / 결과·배운 점 / 질문·직무 연결 네 기준을 행동 기준(앵커)이 붙은 3단계(충분·일부·부족)로 봅니다. 점수가 아니라 근거를 대는 코치가 목표라서, 모든 판단에 전사문 인용을 붙이고 서버가 그 인용이 실제 전사문에 있는지 확인합니다(없으면 인용을 빼고, 근거 없는 '충분'은 '일부'로 낮춤). 질문 유형(경험·가상 상황·자기소개류·지식·인적성)에 따라 '해당 없음'을 서버가 정하고, 채점은 생성과 다른 프롬프트로 temperature 0.2에서 합니다. 목소리·표정·감정은 보지 않고 말한 내용만 봅니다. 채점 기준은 화면에서 펼쳐 볼 수 있습니다.
- **세션 종료 자동 디브리프와 약점 재연습.** 세션이 끝나면 백그라운드에서 답변을 채점하고 '핵심 교훈 · 다음 행동 · 주목할 순간(전사문 인용)'을 만듭니다. 자기평가 2점 이하, 루브릭 '부족', 건너뛴 질문을 모아 한 번에 다시 연습할 수 있고, 다시 연습한 세션에는 지난번 결과가 함께 보입니다.

근거와 한계: LLM 채점과 전문가 채점의 일치도는 Kendall's τ=.19–.44로 높지 않아서(화면에도 '참고용'으로 표시), 점수 대신 인용과 개선 문장을 보여 줍니다. 녹화를 다시 보기만 한 집단은 나아지지 않고 자동 분석 피드백을 함께 받은 집단만 나아졌다는 연구(MACH, N=90)가 자동 디브리프의 근거입니다.

![녹음 동의](docs/screenshots/p0-consent.png)
![세션 디브리프](docs/screenshots/p0-debrief.png)

**통과율 정의:** `통과 ÷ (통과 + 탈락)`. 결과가 아직 안 나온 건을 분모에 넣으면 통과율이 실제보다 낮게 나오므로 따로 셉니다.

## 실행 방법

### 1) 백엔드
```bash
cd backend
python3 -m pip install -r requirements.txt
cp .env.example .env        # 값을 비워 두면 로컬 SQLite + 로그인 없이 동작
python3 -m uvicorn app.main:app --reload --port 8000
# API 문서: http://localhost:8000/docs
python3 -m pytest -q        # 테스트
```

### 2) 웹
```bash
cd web
npm install
npm run dev                 # http://localhost:5173
```

### 3) 크롬 확장 팝업
`chrome://extensions` → 개발자 모드 → 압축해제된 확장 프로그램 로드 → `extension-track` 폴더. 자세한 내용은 [extension-track/README.md](extension-track/README.md).

### 4) Supabase 연결(배포 시)
1. Supabase SQL Editor에서 `supabase/schema.sql` 실행. 이미 예전 스키마로 만든 프로젝트라면 `supabase/migrations/20261015_practice_p0.sql`을 실행하면 됩니다(여러 번 실행해도 안전). 로컬 SQLite는 서버를 켤 때 빠진 컬럼을 자동으로 추가합니다.
2. `backend/.env`에 `DATABASE_URL`(Connection string), `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` 입력, `AUTH_DISABLED=false`
3. `OPENAI_API_KEY`를 넣으면 맞춤 질문(LLM), 전사(STT), 루브릭 피드백과 자동 디브리프가 켜집니다. 모델은 `OPENAI_CHAT_MODEL`(질문 생성), `OPENAI_FEEDBACK_MODEL`(채점·디브리프, 비우면 질문 생성 모델), `OPENAI_STT_MODEL`로 바꿀 수 있어요. 원본 녹음 보관 기한은 `AUDIO_RETENTION_DAYS`, 만료 정리 주기는 `PURGE_INTERVAL_MIN`입니다.

키가 없어도 앱은 동작합니다. 맞춤 질문은 자소서 문장에서 경험 서술을 골라 만드는 규칙 기반으로 대체되고, 전사문은 직접 입력할 수 있습니다.

## 팀원과 맞물리는 부분

- **로그인(1단계 계정·DB 담당):** 웹에서 Supabase 로그인 후 `setAuthTokenProvider(async () => (await supabase.auth.getSession()).data.session?.access_token ?? null)`만 호출하면 모든 API에 토큰이 붙습니다(`web/src/api.ts`). 백엔드는 토큰의 `sub`를 사용자 id로 씁니다.
  - Supabase 프로젝트가 비대칭 JWT 서명 키(JWKS)를 쓰도록 설정돼 있다면 `backend/app/auth.py`의 HS256 검증을 JWKS 검증으로 바꿔야 합니다.
- **① Apply(크롬 확장):** 지원서 제출 시 `POST /track/sync`로 아래 형식을 보내면 Track에 저장됩니다. 예전 답변 재사용은 `GET /track/answers/search?q=키워드`를 쓰면 됩니다. CORS는 `chrome-extension://` 출처를 허용해 두었습니다.
  ```json
  {"company":"토스","position":"서버 개발자","job_category":"개발","url":"https://...",
   "essays":[{"question_text":"지원 동기","content":"...","char_limit":500}],"submitted":true}
  ```
- **④ Encourage:** 화면 상단 레이아웃(`web/src/App.tsx`)에 팝업 컴포넌트를 끼우면 됩니다.

## 주요 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET/POST | `/practice/questions` | 질문은행 조회(분류·직무·출처 필터) / 직접 추가 |
| POST | `/practice/questions/generate` | 맞춤 질문 생성 |
| POST/GET | `/practice/sessions` | 연습 세션 생성(자유·모의) / 목록 |
| GET | `/practice/sessions/{id}` | 세션 상세 |
| POST | `/practice/answers/{id}/audio` | 녹음 업로드 + 전사 |
| PATCH | `/practice/answers/{id}` | 자기평가·회고·전사문 수정 |
| POST | `/practice/answers/{id}/feedback` | 루브릭 피드백 |
| GET | `/practice/rubric` | 채점 기준 |
| GET/PUT | `/practice/settings` | 녹음 동의·원본 보관 설정(동의 철회 시 원본 삭제) |
| DELETE | `/practice/recordings` | 내 원본 녹음 모두 삭제 |
| DELETE | `/practice/answers/{id}/audio` | 답변 하나의 원본 녹음 삭제 |
| POST | `/practice/sessions/{id}/finish` | 세션 종료 + 자동 디브리프 |
| POST | `/practice/sessions/{id}/debrief` | 디브리프 다시 만들기 |
| POST | `/practice/sessions/{id}/redrill` | 약점 질문으로 새 세션 |
| GET/POST | `/track/applications` | 지원 건 목록(`url`로 찾기 가능) / 추가 |
| POST | `/track/applications/{id}/events` | 단계 결과 기록 |
| POST | `/track/applications/{id}/essays` | 자소서 문항 추가 |
| POST | `/track/essays/{id}/versions` | 새 답변 버전 |
| POST | `/track/versions/{id}/restore` | 예전 버전 복원 |
| POST | `/track/sync` | 확장 프로그램 동기화 |
| GET | `/track/stats` | 통계 |

## 검증한 것

- 백엔드 pytest 68개 통과(사용자 간 데이터 격리, 버전 중복 방지, 동기화 upsert, 통과율 계산, 녹음 동의·원본 삭제·만료 정리·삭제 실패 재시도, 인용 검증, 질문 유형 판별(공용 질문 30개 전부), 채점 중 전사문 수정 경합, 디브리프·재연습. OpenAI 경로는 모의 응답으로 확인)
- 가짜 마이크와 가짜 OpenAI 서버로 동의 → 녹음 → 자동 디브리프 → 루브릭 피드백 → 약점 재연습 → 설정(보관·모두 지우기·동의 철회), 키 없는 모드, 전사 실패·디브리프 실패 같은 실패 경로까지 브라우저에서 134개 항목 확인. 390px 폭에서 가로 스크롤 없음
- 로컬 Postgres 16(Supabase 흉내)에 `schema.sql`과 마이그레이션을 적용해 백엔드 흐름 확인. 이 과정에서 id 컬럼이 Postgres에서 uuid로 바인딩되지 않아 서버가 시작하지 못하던 기존 문제도 고쳤습니다
- Chromium + 가짜 마이크로 지원 건 추가 → 자소서 2개 버전·비교 → 단계 기록 → 맞춤 질문 생성 → 모의시험 녹음 2건 → 회고 저장 → 통계까지 실제 화면에서 확인. 콘솔 에러 없고 모바일 폭(390px)에서 가로 스크롤 없음
- 크롬에 확장을 올려 공고 저장 → 같은 공고 재인식 → 대시보드 열기까지 확인(테스트용 가짜 공고 페이지 사용, 실제 채용 사이트에서는 아직 시험 전)
- 실제 OpenAI 키와 Supabase 프로젝트로는 아직 시험하지 않았습니다
