# 아키텍처

2026-10-28, `feature/practice-p0`(1a12453) 소스 기준. 기능 설명과 API 표는 [README](../README.md)를 봅니다. 이 문서는 구성 요소 사이의 연결과 데이터가 머무는 곳을 다룹니다.

## 구성

```
 web (React, Vite :5173) ─┐
                          ├─ HTTP/JSON, Bearer(배포) 또는 X-User-Id(개발) ──▶ backend (FastAPI :8000)
 extension-track (MV3) ───┘                                                    │
                                                                               ├─ DB: SQLite(backend/jobseeker.db) 또는 Supabase Postgres(DATABASE_URL)
                                                                               ├─ 녹음: backend/recordings/ 또는 Supabase Storage 버킷 "recordings"
                                                                               └─ OpenAI(선택): /chat/completions, /audio/transcriptions
```

- 웹과 확장은 백엔드만 호출합니다. Supabase나 OpenAI에 직접 붙지 않습니다.
- 각 외부 서비스는 설정이 비어 있으면 로컬 대체 경로로 동작합니다(`app/config.py`가 `backend/.env`를 읽음).

| 설정 | 비었을 때 | 있을 때 |
|---|---|---|
| `DATABASE_URL` | 로컬 SQLite, 시작 시 테이블·빠진 컬럼 자동 추가 | Postgres. 스키마는 `supabase/` SQL로 미리 만들어야 함 |
| `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` | `backend/recordings/` | Storage REST API(서비스 키) |
| `OPENAI_API_KEY` | 규칙 기반 질문, 기본 점검, 전사·디브리프 요약 없음 | LLM 질문·코칭·꼬리질문·디브리프 요약, STT |
| `AUTH_DISABLED=true`(기본, **로컬 개발 전용**) | `X-User-Id` 헤더 또는 고정 dev 사용자. 헤더만 바꾸면 누구로든 접근 가능 | `false`(배포 시 필수)면 Supabase JWT(HS256, aud `authenticated`)의 `sub` |

## 백엔드 (`backend/app/`)

| 모듈 | 역할 |
|---|---|
| `main.py` | 앱 생성, CORS(`CORS_ORIGINS` + `chrome-extension://*`), 시작 시 DB 준비·질문은행 시드·만료 녹음 정리 루프, `/health` |
| `routers/practice.py` | `/practice/*`: 질문은행, 세션, 답변·녹음·전사, 코칭, 꼬리질문, 디브리프, 다시 연습, 설정 |
| `routers/track.py` | `/track/*`: 지원 건, 단계 이벤트, 자소서 문항·버전, 검색, 확장 동기화, 통계 |
| `models.py` / `schemas.py` | SQLAlchemy 모델 / Pydantic 입출력 |
| `db.py` | 엔진, SQLite 자동 업그레이드(`upgrade_sqlite`) |
| `auth.py` | `current_user_id` 의존성 |
| `llm.py` | OpenAI 호출(`httpx` 직접 호출, SDK 없음), 템플릿 질문 대체, 인용 원문 대조(`verify_quote`) |
| `coaching.py` | 면접 시작 시 기준 자료 스냅샷, 채점 기준(`RUBRIC`, `RUBRIC_VERSION`), 코칭 보고서 생성(AI 또는 기본 점검) |
| `debrief.py` | 세션 종료 후 디브리프 작업, 다시 연습 대상 선정 |
| `retention.py` | 원본 녹음 삭제·만료 정리·고아 파일 정리 |
| `storage.py` | 녹음 저장소 추상화(로컬/Supabase) |
| `seed.py` | 공용 질문은행 시드 |

## 인증과 데이터 접근 경계

API의 JWT 검증과 DB의 RLS는 서로 다른 장치이고, 현재 코드에서 둘은 연결돼 있지 않습니다. 아래 "확인된 사실"은 2026-10-28 소스를 읽고 확인한 것이고, "검증하지 않음"은 실제 Supabase에서 확인하지 않은 것입니다.

확인된 사실(코드 기준):
- **API 인증:** `app/auth.py`의 `current_user_id`가 `AUTH_DISABLED=false`일 때 Bearer 토큰을 `SUPABASE_JWT_SECRET`으로 검증(HS256, aud `authenticated`)하고 `sub`를 사용자 id로 돌려줍니다. 검증은 API 계층에서 끝납니다.
- **사용자 id는 DB 세션으로 전달되지 않습니다.** 백엔드는 `DATABASE_URL` 하나로 만든 공용 SQLAlchemy 엔진을 씁니다(`app/db.py`). 요청마다 `set_config('request.jwt.claims', …)`나 `SET LOCAL role` 같은 처리를 하지 않습니다(`backend/app`에 해당 코드 없음).
- **실제 사용자 격리는 라우터 쿼리가 담당합니다.** 모든 조회·수정이 `user_id`(또는 소유한 세션·지원 건)로 거릅니다. 다른 사용자의 데이터를 읽거나 고칠 수 없다는 것은 pytest(SQLite)로 검증했습니다.
- **`supabase/schema.sql`의 RLS 정책**은 `auth.uid()`로 소유자를 비교합니다. 이 정책은 Supabase 클라이언트(anon/authenticated 역할 + 사용자 JWT)로 직접 접속하는 경우를 막는 장치입니다.
- **Storage:** 백엔드는 `SUPABASE_SERVICE_ROLE_KEY`로 Storage REST API를 호출합니다(`app/storage.py`). 서비스 키는 RLS를 우회하므로 `storage.objects`의 `rec_own` 정책은 백엔드 요청에 적용되지 않습니다. 녹음 객체 접근을 막는 것은 API의 소유권 검사와 경로 규칙(`{user_id}/{session_id}/{answer_id}.{ext}`)입니다. 그래서 녹음 API를 고칠 때 소유권 검사를 빠뜨리면 다른 사용자의 녹음이 노출될 수 있습니다.
- **`AUTH_DISABLED=true`**는 로컬 개발용입니다. 이 상태에서는 `X-User-Id` 헤더 값이 곧 사용자이므로, 배포 환경에서는 반드시 `false`로 둡니다.

검증하지 않음(운영 보장으로 쓰지 말 것):
- 백엔드의 Postgres 접속 역할(`DATABASE_URL`의 사용자)이 RLS를 적용받는지, 우회하는지(테이블 소유자·`postgres`·`BYPASSRLS` 역할이면 우회함).
- 백엔드 DB 연결에서 `auth.uid()`가 어떤 값을 내는지. 위 이유로 JWT 클레임이 전달되지 않으므로 null일 가능성이 높지만 실제로 확인하지 않았습니다. 만약 접속 역할에 RLS가 적용된다면 정책 때문에 쿼리가 빈 결과를 낼 수도 있습니다.
- 실제 운영 Supabase 프로젝트에 RLS·Storage 정책이 적용됐는지, 의도대로 동작하는지.

따라서 현재 보장할 수 있는 사용자 격리는 "API를 거치는 요청에 대해 라우터의 소유권 검사가 동작한다(테스트 기준)"까지입니다. RLS를 백엔드의 두 번째 방어선으로 쓰려면 요청마다 JWT 클레임을 DB 세션에 넘기고 비특권 역할로 접속하도록 바꾼 뒤 실제 Supabase에서 검증해야 합니다(설계 결정 필요).

## 데이터베이스

테이블(정의: `models.py`, Postgres: `supabase/schema.sql`)

| 영역 | 테이블 | 비고 |
|---|---|---|
| Practice | `questions` | `user_id` null이면 공용 질문은행. `source`: bank/custom/generated(꼬리질문도 generated) |
| | `practice_private_questions` | 답변에 따라 만든 꼬리질문 표시. 다른 세션 질문은행에 섞이지 않게 함 |
| | `practice_sessions` | 모드·시간 설정, `debrief`(JSON), `debrief_status`(none/pending/done/failed/unavailable), 작업 시각·heartbeat |
| | `practice_answers` | 전사문, 자기평가, 회고, `audio_path`, `recorded_at`/`audio_expires_at`/`audio_deleted_at` |
| | `practice_contexts` | 면접 시작 시 고정한 회사·직무·자소서 버전 본문·공고 스냅샷 |
| | `answer_coaching` | 코칭 보고서(JSON, 전사문 지문 포함), 꼬리질문의 부모 답변 |
| | `user_settings` | 녹음 동의 시각, 원본 보관 여부, 삭제 요청 시각 |
| Track | `applications` → `stage_events`, `essay_items` → `answer_versions` | 지원 건, 단계 결과, 자소서 문항별 버전 이력 |

스키마 적용 경로:
- 로컬 SQLite: 서버 시작 시 `create_all` + 빠진 컬럼 `ALTER TABLE ADD` + 예전 녹음 행 보정.
- 새 Supabase 프로젝트: `schema.sql` 한 번.
- 기존 Supabase 프로젝트: `migrations/20261015_interview_coaching.sql`, `20261015_practice_p0.sql`(서로 독립, 재실행 안전). 자동 마이그레이션 도구는 없습니다.

## 주요 흐름

**면접 연습**
1. `POST /practice/sessions`: 지원 건이 있으면 제출본(없으면 최신본) 자소서를 골라 `practice_contexts`에 복사합니다. 이후 자소서를 고쳐도 이 세션의 기준은 바뀌지 않습니다.
2. 답변: 글로 쓰면 `PATCH /practice/answers/{id}`. 녹음은 `POST .../audio`로 올립니다(동의 없으면 403). 저장 경로는 `{user_id}/{session_id}/{answer_id}.{ext}`이고, 키가 있으면 STT로 전사합니다. 전사에 성공하고 보관 설정이 꺼져 있으면 원본을 바로 지웁니다.
3. `POST .../coach`: 키가 있으면 LLM이 3개 기준으로 채점하고 서버가 인용을 원문과 대조합니다. 대조에 실패하거나 호출이 실패하면 기본 점검으로 바꿉니다. `POST .../followup`: 원 질문당 꼬리질문 1개.
4. `POST /practice/sessions/{id}/finish`: FastAPI `BackgroundTasks`로 디브리프를 시작합니다. 코칭이 없는 답변을 점검한 뒤, 키가 있으면 요약(핵심 교훈·다음 행동·주목할 순간)을 만듭니다. 작업은 heartbeat를 남기고, 5분 넘게 끊긴 경우에만 새 작업이 이어받습니다. 작업은 프로세스 안에서 돌기 때문에 서버가 재시작되면 사라지고, 화면은 다시 시도 버튼을 보여 줍니다.
5. `POST .../redrill`: 보완 판정을 받은 답변과 자기평가 1~2점 답변(최대 20개)으로 새 세션을 만듭니다.

**녹음 보관:** 앱 시작 시 한 번, 이후 `PURGE_INTERVAL_MIN`분마다 만료된 원본과 고아 파일(답변이 가리키지 않는 저장소 파일)을 지웁니다. 동의 철회와 "모두 지우기"는 즉시 지웁니다. 지우지 못한 파일은 `sweep_audio_before`에 남겨 다음 정리 때 다시 지웁니다.

**Track·확장:** 확장 팝업은 현재 탭의 `og:title`/`<title>`에서 회사·직무를 추정합니다(`extract.js`). 사용자가 확인하면 `POST /track/sync`를 보냅니다. 서버는 URL로 기존 지원 건을 찾아 갱신하거나 새로 만들고, 내용이 바뀐 자소서 문항만 새 버전으로 쌓습니다. 확장은 아직 토큰을 보내지 않습니다(`api.js`의 `getToken()`이 null을 돌려줌).

## 웹 (`web/src/`)

라우트는 `App.tsx`에 있습니다: `/practice`, `/practice/history`, `/practice/settings`, `/practice/sessions/:id/run`, `/practice/sessions/:id`, `/track`, `/track/stats`, `/track/:id`. API 호출은 모두 `api.ts`를 거칩니다(`VITE_API_URL`, `setAuthTokenProvider`). 녹음은 `components/useRecorder.ts`(MediaRecorder)가 맡습니다. `/health`의 `openai` 값에 따라 AI 기능 안내와 디브리프 생성 버튼을 보여 줍니다.

## 현재 구현이 아닌 것 (계획·연동 대기)

- 웹 로그인 UI와 Supabase Auth 연결: 1단계 담당 팀원 몫. `setAuthTokenProvider` 연결 지점만 있습니다.
- JWKS(비대칭 JWT) 검증: 현재는 HS256만 지원합니다.
- ① Apply 확장의 지원서 제출 자동 감지와 essays 전송: 팀원 몫. 이 저장소의 확장은 공고 저장만 하고 `essays: []`를 보냅니다.
- ④ Encourage 팝업: 팀원 몫. `App.tsx`에 끼울 자리만 언급돼 있습니다.
- 디브리프 작업 큐: 별도 워커 없이 프로세스 안의 BackgroundTasks로 돕니다.
- 배포 설정(호스팅, CI): 저장소에 없습니다.
