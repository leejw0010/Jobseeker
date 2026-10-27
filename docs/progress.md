# 진행 상태

최종 갱신: 2026-10-28. 갱신할 때는 날짜와 근거(명령·커밋)를 함께 적고, 오래된 항목은 지우거나 "완료"로 옮깁니다. 아래에서 "구현 사실", "자동 테스트", "외부 서비스 실검증"을 구분해 적습니다.

## 현재 브랜치 상태

- `main`: PR #1(확장 팝업)과 PR #2(`codex/evidence-interview-coach`, 제출본 기반 면접 코칭)까지 머지됨.
- `feature/practice-p0`(작업 중): `main`보다 8커밋 앞서 있고 `origin/feature/practice-p0`와 같음(1a12453). P0 기능과 리뷰 지적 1~21번, 재확인 지적 수정까지 끝났음.
- **PR #3:** https://github.com/leejw0010/Jobseeker/pull/3 · `feature/practice-p0` → `main` · 2026-10-28 GitHub API(`GET /repos/leejw0010/Jobseeker/pulls/3`)로 확인한 당시 **Open, 미병합, draft 아님**, head 1a12453. (`gh`는 설치돼 있지 않음.)
- 추적하지 않는 파일: `.vscode/`(개인 설정). `backend/.venv/`는 2026-10-28에 `.gitignore`에 추가함.

## 1. 구현 사실 (코드로 확인)

| 기능 | 위치 |
|---|---|
| Practice: 질문은행·맞춤 질문·모의시험·녹음/글 답변·전사·회고 | `routers/practice.py`, `web/src/pages/Session*.tsx` |
| 제출본 기반 코칭, 인용 대조, 꼬리질문(1회), 다시 연습 | `app/coaching.py`, `app/llm.py:verify_quote` |
| P0: 녹음 동의(403), 전사 후 원본 삭제, 보관 기한·만료·고아 파일 정리, 동의 철회, 설정 화면 | `app/retention.py`, `web/src/components/ConsentPanel.tsx`, `web/src/pages/PracticeSettings.tsx` |
| P0: 자동 디브리프(heartbeat, 중복 작업 방지, 실패 재시도), 자기평가 기반 다시 연습 | `app/debrief.py` |
| Track: 지원 건·단계·버전·복원·sync·통계 | `routers/track.py` |
| Track: 자소서 버전 단어 단위 diff | 프런트엔드 `web/src/components/Diff.tsx`(백엔드에는 diff 로직 없음) |
| 인증: JWT(HS256) 검증 후 `sub` 사용, 라우터에서 `user_id` 필터 | `app/auth.py`, `routers/*` ([architecture.md](architecture.md) "인증과 데이터 접근 경계") |

## 2. 자동 테스트 (외부 서비스 없이)

| 대상 | 테스트 | 검사하는 것 / 검사하지 않는 것 |
|---|---|---|
| 코칭·인용 대조·꼬리질문·다시 연습 | `test_interview_coaching.py`, e2e 시나리오 1 | OpenAI는 모의 응답 |
| 녹음 동의·원본 삭제·만료·고아 파일·동의 철회 API | `test_privacy.py` | 서버 동작. 설정 화면 UI는 e2e가 열지 않음 |
| 녹음 동의 화면(`ConsentPanel`) | e2e 시나리오 2·4·5(동의 없는 상태로 시작해 `동의하고 시작` 버튼을 눌러 녹음 시작) | 동의 패널이 뜨고 동의 후 녹음이 시작되는 것 |
| 자동 디브리프·다시 연습 | `test_debrief.py`, e2e 시나리오 1 | e2e는 키 없는 모드에서 디브리프가 남은 답변을 기본 점검하는 것과 작업 종료(`debrief_running`)만 확인. AI 요약 카드는 e2e 대상 아님 |
| STT 요청 형식·재시도·오류 처리 | `test_transcription.py`, e2e 시나리오 5 | 모의 응답. 실제 인식 정확도는 아님 |
| 잘못된 id → 404 | `test_malformed_ids.py` | |
| 스키마 | `test_migration.py` | **로컬 SQLite 업그레이드**와 **id 컬럼의 Postgres `UUID` 타입 컴파일**만 검사. Supabase SQL 실행·RLS·Storage 정책은 검사하지 않음 |
| Track: 지원 건·단계·버전 중복 방지·복원·sync upsert·통계 | `test_track.py` | 백엔드 API만. 프런트엔드 단어 diff(`Diff.tsx`)는 pytest·e2e 모두 직접 검증하지 않음 |

2026-10-28에 직접 실행한 결과:
- `backend/.venv/bin/python -m pytest -q` → **136 passed**, 경고 1개(Starlette TestClient의 httpx 사용 중단 예고).
- `cd web && npm run build` → 통과.
- `npm run test:e2e` → **10 passed**(desktop·mobile 각 5개). 설치된 Playwright 브라우저가 1208이고 패키지는 1248을 요구해서 `CHROMIUM_EXECUTABLE_PATH=~/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome`를 지정해 실행했음.

README에 적힌 다른 수동 확인(가짜 OpenAI 서버로 145개 항목, 로컬 Postgres 16, 확장을 크롬에 올려 본 확인)은 이번에 다시 실행하지 않았습니다.

## 3. 외부 서비스 실검증 (아직 안 함)

- OpenAI: 실제 키로 STT 정확도, 코칭·꼬리질문·디브리프 응답 품질, JSON 형식 준수를 확인하지 않음. 테스트는 모두 모의 응답이나 가짜 서버로 돌림.
- Supabase: 실제 프로젝트에서 `schema.sql`·마이그레이션 실행, RLS 적용 여부와 백엔드 접속 역할의 RLS 우회 여부, 백엔드 연결에서 `auth.uid()` 값, Storage 업로드·목록·삭제와 정책, JWT 인증을 확인하지 않음. 백엔드 Postgres 경로는 로컬 Postgres 16으로만 확인함(README 기록, RLS는 대상 아님).
- 확장: 실제 채용 사이트(사람인·원티드 등)에서 제목 추출을 시험하지 않음(테스트용 가짜 공고 페이지만).

## 보안 검토 필요

- **React Router 취약점(2026-10-28 `npm audit`):** 설치본 `react-router-dom@6.30.6`·`react-router@6.30.6`(package.json `^6.28.0`)이 두 권고의 영향 범위(6.0.0~7.17.0)에 들어 Moderate 2건으로 보고됨. 수정 버전은 7.18.0 이상이고 `npm audit fix --force`는 7.x 메이저 업그레이드(호환성 깨짐)라서 실행하지 않았음. 이전 리뷰(P2-8)의 "영향 없음" 판단은 틀렸으므로 이 기록으로 대체함.
  - GHSA-337j-9hxr-rhxg(SSR 하이드레이션의 `deserializeErrors()`): 이 앱은 `BrowserRouter` 기반 Declarative Mode(`web/src/main.tsx`)이고 SSR을 쓰지 않으므로 해당하지 않는 것으로 판단.
  - GHSA-wrjc-x8rr-h8h6(`<Link>`·`useNavigate`의 백슬래시 오픈 리다이렉트): SSR과 무관하므로 위 판단으로 배제되지 않음. 코드 검색(grep) 기준으로 `Link`/`nav()`에 넘기는 값은 고정 경로와 서버가 준 id뿐이고 URL 쿼리 등 사용자 입력을 경로로 넘기는 곳은 찾지 못했음. 정식 검토와 7.x 업그레이드 여부는 결정 전.

## 미해결 문제

- e2e를 실행하면 추적 중인 `docs/screenshots/coaching-review-{desktop,mobile}.png`를 덮어씀(`web/e2e/coaching.spec.ts:70`). 지금은 AGENTS.md의 백업·복원 절차로 대응. **추후 테스트 수정 필요:** 스크린샷 경로를 환경 변수로 받거나 기본값을 `test-results/`로 바꾸고, 문서용 갱신은 명시적으로 켤 때만 하도록.
- e2e 설정은 PATH의 `python`을 씀. venv를 PATH에 넣지 않으면 백엔드가 뜨지 않음.
- 로컬 Playwright 브라우저 버전이 패키지와 안 맞음(위 참고).
- 확장 `api.js`에 인증 토큰이 없어서 `AUTH_DISABLED=false` 환경에서는 401이 남.
- 디브리프 작업은 서버 재시작 시 사라짐(설계상 재시도로 복구, [decisions.md](decisions.md) D-13).
- 백엔드 DB 연결에 RLS가 두 번째 방어선으로 동작하지 않을 수 있음([architecture.md](architecture.md) "인증과 데이터 접근 경계").
- [decisions.md](decisions.md)의 외부 근거(논문·기업 정책·법 조문) 원문을 아직 확인하지 않음.

## 해결됨 (2026-10-28)

- README 테스트 수치(구조도 "80개", 검증 절 "126개")를 실제 결과 136개에 맞춤.
- `.gitignore`에 `.venv/`, `.env.*`(단 `.env.example` 제외) 추가. `backend/.env.example`·`web/.env.example`에는 비밀값이 없음(값이 비어 있거나 모델명·URL 같은 기본값만 있음, 값은 출력하지 않고 확인).

## 다음 우선순위 (제안, 사용자 확정 전)

1. PR #3(`feature/practice-p0` → `main`) 검토·머지(사용자 결정).
2. 실제 OpenAI 키로 STT·코칭 품질 확인, 결과를 이 문서에 기록.
3. 실제 Supabase 프로젝트에 스키마·마이그레이션을 적용하고 RLS·Storage·JWT 확인. 백엔드 접속 역할과 `auth.uid()` 값 확인. JWKS를 쓰는 프로젝트라면 `auth.py` 수정.
4. React Router 7.x 업그레이드 여부 결정과 GHSA-wrjc 정식 검토.
5. e2e 스크린샷 경로 분리(테스트 수정).
6. 팀원 연동: 웹 로그인 토큰 제공자, ① Apply 확장의 `/track/sync` essays 전송, 확장 `getToken()`.

## 이어서 작업할 때

- 환경: WSL2 Ubuntu, Python 3.12 venv(`backend/.venv`), `web/node_modules`가 설치돼 있음. `backend/.env`가 있음(내용은 열지 말 것).
- 기능 배경은 [docs/plans/2026-10-15-evidence-interview.md](plans/2026-10-15-evidence-interview.md)와 README의 "연습 전용 원칙과 P0 기능" 절에 있음. 경쟁 분석 보고서(`research/reports/Final Round AI 경쟁 분석.md`)는 프로젝트 공유 폴더에 있고 이 저장소에는 없음.
