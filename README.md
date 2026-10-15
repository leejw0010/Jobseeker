# JobSeeker: ② Practice · ③ Track

## 제출본 기반 면접 코칭 (2026-10-15)

- 면접 설정에서 **제출본 우선 / 최신본**을 선택합니다. 제출 표시가 없는 문항은 최신본을 사용하며 화면에 표시합니다. 면접을 시작하면 회사·직무·자소서 버전과 본문·입력한 채용 요건을 별도로 보관합니다.
- 녹음 또는 **글로 답변**할 수 있습니다. 답변을 확인한 뒤 **꼬리질문 받기** 또는 다음 질문을 선택합니다. 꼬리질문은 원 질문당 한 번이며 이전 답변에 따른 질문이 다른 면접의 질문은행에 섞이지 않습니다.
- 회고의 **답변 점검**에서 구체성·질문 적합성·제출본 연결을 확인합니다. AI가 제시한 답변/자소서 인용은 실제 원문과 대조합니다. API 키가 없거나 호출/인용 검증에 실패하면 **기본 점검**으로 표시하며 의미·진위를 판정하지 않습니다.
- **보완 항목 다시 연습**은 같은 기준 자료와 질문으로 새 세션을 만듭니다. 기존 녹음·답변·회고는 보존합니다.
- 기존 SQLite DB는 서버를 다시 시작하면 새 테이블이 추가됩니다. 기존 Supabase 프로젝트는 [증분 마이그레이션](supabase/migrations/20261015_interview_coaching.sql)을 SQL Editor에서 실행해야 합니다(기존 데이터 삭제 없음).

추가 API: `POST /practice/answers/{id}/coach`, `POST /practice/answers/{id}/followup`, `POST /practice/sessions/{id}/redrill`.

### 음성 인식·자동 전사

원래 ② Practice의 `Recording & Transcription`에 해당합니다. 브라우저에서 녹음한 답변을 저장한 뒤, 서버가 OpenAI 음성 인식 API로 보내 한국어 전사문을 받아 옵니다. 인식한 문장을 사용자가 확인·수정한 다음 꼬리질문과 답변 점검에 사용합니다.

서버의 `backend/.env`에 `OPENAI_API_KEY`를 설정하고 재시작하면 자동 전사가 활성화됩니다. 기본 모델은 `OPENAI_STT_MODEL=whisper-1`이며 키는 프런트엔드에 넣지 않습니다. 키가 없으면 녹음 저장·재생과 글 답변·기본 점검은 사용할 수 있습니다.

- WebM/MP4 등 파일 형식에 맞는 메타데이터를 전송하고, 재시도에서도 원래 형식을 유지합니다.
- 음성을 인식하지 못하거나 잘못된 응답이 오면 완료로 처리하지 않으며, 녹음을 보관해 다시 시도할 수 있습니다.
- 재시도가 실패하면 사용자가 고친 전사문을 유지합니다.
- 음성 인식 서버의 응답을 기다리는 동안 다른 API 요청을 막지 않습니다.

음성 인식 응답을 대체한 테스트로 요청 형식·저장·재시도·오류 처리를 검증합니다. 실제 녹음에 대한 인식 정확도는 실제 API 키를 연결한 후 별도 확인해야 합니다.

[서비스 동작 조사 및 REA 실행 기록](docs/research/interview-products-2026-10-15.md)에는 공개 자료에서 확인한 기능, 실제 분석 명령, 분석이 중단된 환경 조건을 구분해 두었습니다.

브라우저 통합 테스트(백엔드 Python 의존성이 설치된 가상환경에서):

```bash
cd web
npm ci
npx playwright install chromium
npm run test:e2e
```

테스트는 임시 SQLite DB와 전용 포트(8011, 5179)의 서버를 실행하며 기존 개발 서버를 재사용하지 않습니다. `CHROMIUM_EXECUTABLE_PATH`로 기존 Chromium을 지정할 수도 있습니다. 실제 OpenAI 코칭 품질 및 운영 Supabase 연결은 별도 검증이 필요합니다.

캡스톤 설계(26-2) JobSeeker 중 **② AI 인적성·면접 연습**과 **③ 지원 이력·버전 관리** 부분입니다.
발표자료의 스택(React+TS, FastAPI, Supabase, OpenAI)을 그대로 따랐습니다.

```
jobseeker/
├─ supabase/schema.sql   Supabase에 붙여 넣을 테이블·RLS·Storage 버킷
├─ backend/              FastAPI (Practice·Track API, 테스트 40개)
├─ web/                  React + TypeScript (Vite) 웹 화면
├─ extension-track/      크롬 확장 팝업 (공고 저장, 최근 지원 현황, 대시보드 열기)
└─ docs/screenshots/     실제 실행 화면
```

## 구현한 기능

| 발표자료 항목 | 구현 내용 |
|---|---|
| ② Question Bank & Tailored Questions | 공용 질문은행 30문항(인성·직무·기업·상황·인적성, 직무별), 직접 추가, 지원 건(회사·직무·선택한 기준 자소서)으로 맞춤 질문 생성, 같은 질문 중복 저장 방지 |
| ② Mock Test Mode | 질문 수·준비 시간·답변 제한 시간 설정. 자기소개로 시작하고, 준비 시간이 끝나면 자동 녹음, 제한 시간이 되면 자동 종료 |
| ② Recording & Transcription | 브라우저 MediaRecorder 녹음(마이크 입력 레벨 표시), Supabase Storage(또는 로컬) 저장, OpenAI STT 전사, 실패 시 재시도 |
| ② Review & Reflection | 녹음 다시 듣기, 전사문 수정, 별점 자기평가, 회고 메모, AI 피드백(잘한 점·보완할 점), 분당 발화 글자 수, 연습 기록 목록 |
| ③ Application Records & Stage Outcomes | 지원 건 CRUD, 서류→인적성→1차→2차→최종 단계별 결과 기록(합격 시 다음 단계로 자동 진행) |
| ③ Answer Version Management | 자소서 문항별 버전 이력, 제출본 표시, 단어 단위 비교(diff), 예전 버전으로 되돌리기, 글자 수 제한 표시, 예전 답변 검색 |
| ③ Extension & Web Synchronization | `POST /track/sync`: 크롬 확장(①)이 제출한 지원서를 URL 기준으로 저장하고, 내용이 바뀐 문항만 새 버전으로 쌓음 |
| ③ Statistics by Job Category & Stage | 단계별 도달·통과·탈락·대기, 직무 분류별 단계 통과율, 월별 지원 수 |

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
1. Supabase SQL Editor에서 `supabase/schema.sql` 실행
2. `backend/.env`에 `DATABASE_URL`(Connection string), `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` 입력, `AUTH_DISABLED=false`
3. `OPENAI_API_KEY`를 넣으면 맞춤 질문(LLM), 전사(STT), AI 피드백이 켜집니다. 모델은 `OPENAI_CHAT_MODEL`, `OPENAI_STT_MODEL`로 바꿀 수 있어요.

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
| POST | `/practice/answers/{id}/feedback` | AI 피드백 |
| GET/POST | `/track/applications` | 지원 건 목록(`url`로 찾기 가능) / 추가 |
| POST | `/track/applications/{id}/events` | 단계 결과 기록 |
| POST | `/track/applications/{id}/essays` | 자소서 문항 추가 |
| POST | `/track/essays/{id}/versions` | 새 답변 버전 |
| POST | `/track/versions/{id}/restore` | 예전 버전 복원 |
| POST | `/track/sync` | 확장 프로그램 동기화 |
| GET | `/track/stats` | 통계 |

## 검증한 것

- 백엔드 pytest 40개 통과(사용자 간 데이터 격리, 버전 중복 방지, 동기화 upsert, 통과율 계산, OpenAI 경로는 모의 응답으로 확인)
- Chromium + 가짜 마이크로 지원 건 추가 → 자소서 2개 버전·비교 → 단계 기록 → 맞춤 질문 생성 → 모의시험 녹음 2건 → 회고 저장 → 통계까지 실제 화면에서 확인. 콘솔 에러 없고 모바일 폭(390px)에서 가로 스크롤 없음
- 크롬에 확장을 올려 공고 저장 → 같은 공고 재인식 → 대시보드 열기까지 확인(테스트용 가짜 공고 페이지 사용, 실제 채용 사이트에서는 아직 시험 전)
- 실제 OpenAI 키와 Supabase 프로젝트로는 아직 시험하지 않았습니다
