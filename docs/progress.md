# 진행 상태

최종 갱신: 2026-10-30. 갱신할 때는 날짜와 근거(명령·커밋)를 함께 적고, 오래된 항목은 지우거나 "완료"로 옮깁니다. 아래에서 "구현 사실", "자동 테스트", "외부 서비스 실검증"을 구분해 적습니다.

## 현재 브랜치 상태

- `main`: PR #1(확장 팝업)과 PR #2(`codex/evidence-interview-coach`, 제출본 기반 면접 코칭)까지 머지됨.
- `feature/practice-p0`(작업 중): `main`보다 8커밋 앞서 있고 `origin/feature/practice-p0`와 같음(1a12453). P0 기능과 리뷰 지적 1~21번, 재확인 지적 수정까지 끝났음.
- **PR #3:** https://github.com/leejw0010/Jobseeker/pull/3 · `feature/practice-p0` → `main` · 2026-10-28 GitHub API(`GET /repos/leejw0010/Jobseeker/pulls/3`)로 확인한 당시 **Open, 미병합, draft 아님**, head 1a12453. (`gh`는 설치돼 있지 않음.)
- `feature/local-stt`(2026-10-30): `feature/video-analysis`(56e28ac)에서 갈라져 로컬 STT를 추가함.
- 추적하지 않는 파일: `.vscode/`(개인 설정). `backend/.venv/`는 2026-10-28에 `.gitignore`에 추가함.

## 1. 구현 사실 (코드로 확인)

| 기능 | 위치 |
|---|---|
| Practice: 질문은행·맞춤 질문·모의시험·녹음/글 답변·전사·회고 | `routers/practice.py`, `web/src/pages/Session*.tsx` |
| 제출본 기반 코칭, 인용 대조, 꼬리질문(1회), 다시 연습 | `app/coaching.py`, `app/llm.py:verify_quote` |
| P0: 녹음 동의(403), 전사 후 원본 삭제, 보관 기한·만료·고아 파일 정리, 동의 철회, 설정 화면 | `app/retention.py`, `web/src/components/ConsentPanel.tsx`, `web/src/pages/PracticeSettings.tsx` |
| P0: 자동 디브리프(heartbeat, 중복 작업 방지, 실패 재시도), 자기평가 기반 다시 연습 | `app/debrief.py` |
| Track: 지원 건·단계·버전·복원·sync·통계 | `routers/track.py` |
| 카메라 자세 분석(선택, 브라우저 전용·메모리 보관): 얼굴 검출 비율, 화면 이탈 시간, 고개 좌우·숙임 상대 변화 | `web/src/video/`, `web/src/components/useFaceAnalysis.ts`·`CameraPanel.tsx`·`VideoReportCard.tsx` (브랜치 `feature/video-analysis`, 미커밋) |
| 로컬 STT(`STT_PROVIDER=local` 기본, faster-whisper `base`·CPU·INT8, 지연 로딩·재사용·캐시 우선, 한 번에 하나), LLM 키와 분리된 `/health`의 `stt` | `app/stt.py`, `web/src/sttText.ts` (브랜치 `feature/local-stt`, 미커밋) |
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
| 로컬 STT | `test_local_stt.py`(25개) | 가짜 모델 + PyAV로 만든 실제 WebM/Opus. 키 없이 전사·원본 삭제, 지연 로딩 1회·재사용·동시 첫 요청 1회 로딩, 캐시 우선·다운로드 1회, 다운로드/로딩 실패 후 재시도, 라이브러리 import 실패(500이 아니라 `failed`), 무음·깨진 파일·너무 긴 녹음·바쁨·모델 오류, 한 번에 하나 실행, 동의 403, 보관→수정→기본 코칭→녹음 삭제, `off`·미설치, `/health` 분리. **인식 정확도는 검사하지 않음.** e2e는 `STT_PROVIDER=off`로 돌려 로컬 전사를 열지 않음 |
| 잘못된 id → 404 | `test_malformed_ids.py` | |
| 스키마 | `test_migration.py` | **로컬 SQLite 업그레이드**와 **id 컬럼의 Postgres `UUID` 타입 컴파일**만 검사. Supabase SQL 실행·RLS·Storage 정책은 검사하지 않음 |
| 카메라 자세 분석 | e2e `camera.spec.ts`(가짜 검출기 + Chromium 가짜 카메라), `video-metrics.spec.ts`(계산만, 브라우저 없이) | 켜기·끄기·다시 켜기, 회고 수치 표시, 화면을 떠날 때 카메라 트랙 정리, 수치를 API로 보내지 않음, 새로고침하면 사라짐, 카메라 거부·모델 실패 시 기존 흐름 유지. **실제 MediaPipe 모델·실제 얼굴로는 검사하지 않음** |
| Track: 지원 건·단계·버전 중복 방지·복원·sync upsert·통계 | `test_track.py` | 백엔드 API만. 프런트엔드 단어 diff(`Diff.tsx`)는 pytest·e2e 모두 직접 검증하지 않음 |

2026-10-28에 직접 실행한 결과:
- `backend/.venv/bin/python -m pytest -q` → **136 passed**, 경고 1개(Starlette TestClient의 httpx 사용 중단 예고).
- `cd web && npm run build` → 통과.
- `npm run test:e2e` → **10 passed**(desktop·mobile 각 5개). 설치된 Playwright 브라우저가 1208이고 패키지는 1248을 요구해서 `CHROMIUM_EXECUTABLE_PATH=~/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome`를 지정해 실행했음.

README에 적힌 다른 수동 확인(가짜 OpenAI 서버로 145개 항목, 로컬 Postgres 16, 확장을 크롬에 올려 본 확인)은 이번에 다시 실행하지 않았습니다.

`feature/video-analysis`(카메라 자세 분석, 2026-10-28): `npm run build` 통과, `npm run test:e2e` → **21 passed, 5 skipped**(계산 테스트는 desktop에서만). 화면을 떠날 때 카메라를 정리하는 코드를 일부러 빼면 `camera.spec.ts`가 실패하는 것도 확인함. 백엔드는 바꾸지 않아 pytest는 실행하지 않음.

`feature/local-stt`(로컬 STT, 2026-10-30) 직접 실행 결과:
- `backend/.venv/bin/python -m pytest -q` → **161 passed**(기존 136 + `test_local_stt.py` 25). 무음 검사·동시 실행 제한·캐시 우선 조회를 일부러 빼면 각각 1·2·3개가 실패하는 것도 확인함.
- `cd web && npm run build` → 통과.
- `npm run test:e2e` → **21 passed, 5 skipped**. 이 머신에 Playwright 브라우저가 없어 `npx playwright install chromium`(v1248, `~/.cache/ms-playwright`)으로 받았고, sudo가 없어 빠진 시스템 라이브러리(`libnspr4`·`libnss3`·`libasound2t64`)는 `apt-get download` + `dpkg -x`로 임시 폴더에 풀어 `LD_LIBRARY_PATH`로 지정함. 스크린샷은 AGENTS.md 절차로 백업·복원함(실행 전후 `git status` 깨끗).

### 로컬 STT 실측 (2026-10-30, 실제 모델·실제 한국어 음성)

- 환경: WSL2 Ubuntu, 8 vCPU, RAM 3GB, Python 3.12, faster-whisper 1.2.1, CTranslate2 4.8.4, PyAV 19.0.2. `base`·CPU·INT8·4스레드, `OPENAI_API_KEY` 빈 값, `HF_HUB_OFFLINE=1`(캐시만 사용).
- 음성: [Zeroth-Korean](https://huggingface.co/datasets/Bingsu/zeroth-korean) test 분할(CC BY 4.0, 사람이 읽은 한국어 낭독) 앞 20개를 받아 온전한 발화만 이어 붙이고 남는 시간은 무음으로 채워 정확히 30초·60초로 만들고, PyAV로 브라우저 MediaRecorder와 같은 WebM/Opus(48kHz 모노 32kbps)로 인코딩함. **면접 답변처럼 자연스럽게 말한 음성이나 실제 마이크 녹음은 아님.** 측정 스크립트는 저장소에 넣지 않음.
- 전사 시간(모델을 불러 둔 뒤, 2회): beam 5 → 30초 **2.17·2.45초**, 60초 **5.10·4.89초**. beam 1 → 30초 1.50·1.56초, 60초 3.42·3.15초. 모델 로딩은 처음 6.1초, 디스크 캐시가 데워진 뒤 0.5~0.8초.
- 글자 오류율(CER, 공백·문장부호 제외): beam 5 기준 30초 0.106, 60초 0.112, 단일 발화 0.065~0.098. 정답 문장은 숫자를 한글로 적어서("삼 월", "이천 십 팔 년") 모델이 숫자로 적은 것("3월", "2018년")도 오류로 셈 → 실제보다 나쁘게 나옴. 고유명사 오인식 있음("장동련 홍익대"→"장동량 홍잇대", "위촉"→"위쪽").
- 실제 HTTP API(임시 SQLite·임시 녹음 폴더, 키 없음): 동의 없이 업로드 403 → 동의 후 30초 업로드 4.72초(첫 요청, 모델 로딩 포함)·1.75초, 60초 4.34·4.38초, 모두 `done`·원본 자동 삭제 → 전사문 수정 → `/coach` 기본 점검(`basic`) → 보관 켜고 업로드 시 원본 유지·재생 200 → 녹음 삭제 후 재생 404 → 무음 `failed`(원본 유지)·다시 전사도 `failed` → 깨진 파일 `failed` → 같은 답변에 실제 음성 재녹음 `done`. `/health`는 `openai: false`, `stt.state`가 `not_loaded`에서 `ready`로 바뀜.
- 실패 처리(실제 라이브러리): 빈 캐시 + 내려받기 끔 → "캐시에 없고 내려받기가 꺼져 있어요", 빈 캐시 + 네트워크 차단 → "내려받지 못했어요", 망가진 `model.bin` → "불러오지 못했어요", 없는 크기 → "알 수 없는 모델 이름", 10초 무음·10초 잡음 → `no_speech`, 쓰레기 바이트·잘린 WebM → `invalid_audio`.
- 최초 다운로드 → 오프라인 재사용: 빈 임시 캐시에 `tiny`를 실제로 받음(14초, 75MB) → 프록시를 닫힌 포트로 돌려 네트워크를 막은 상태에서 불러와 한국어 전사 성공.
- 브라우저 전 구간(Playwright 스크립트, 저장소에 넣지 않음): Chromium 가짜 마이크에 30초 한국어 WAV를 물려(`--use-file-for-fake-audio-capture`) 동의 → 녹음 31초 → 답변 끝내기 → **11.5초 뒤**(첫 요청이라 모델 로딩 포함) 입력란에 한국어 전사문 표시, 서버 `done`·원본 삭제. 상단 안내 "음성 전사: 이 서버에서 직접 해요(로컬 Whisper base, 외부로 보내지 않음). AI 코칭: 연결되어 있지 않아 기본 점검으로 대신해요.", 동의·설정 화면 문구 확인, 페이지 오류 없음. 헤드리스 셸에 한글 폰트가 없어 스크린샷 글자는 깨져 보임(DOM 텍스트로 확인).
- 동시 부하: 60초 음성 3건 동시 → 대기 제한 2초면 1건 `done`, 2건 `busy`(약 4초 후) / 기본 60초면 3건 모두 `done`(6.3·10.1·14.0초, 한 건씩 차례로).

## 3. 외부 서비스 실검증 (아직 안 함)

- OpenAI: 실제 키로 STT 정확도, 코칭·꼬리질문·디브리프 응답 품질, JSON 형식 준수를 확인하지 않음. 테스트는 모두 모의 응답이나 가짜 서버로 돌림.
- Supabase: 실제 프로젝트에서 `schema.sql`·마이그레이션 실행, RLS 적용 여부와 백엔드 접속 역할의 RLS 우회 여부, 백엔드 연결에서 `auth.uid()` 값, Storage 업로드·목록·삭제와 정책, JWT 인증을 확인하지 않음. 백엔드 Postgres 경로는 로컬 Postgres 16으로만 확인함(README 기록, RLS는 대상 아님).
- 확장: 실제 채용 사이트(사람인·원티드 등)에서 제목 추출을 시험하지 않음(테스트용 가짜 공고 페이지만).
- 카메라 자세 분석: 실제 웹캠·실제 MediaPipe 모델로 시험하지 않음. 아래 수동 검증 항목 참고.
- 로컬 STT: 실제 마이크로 녹음한 자연스러운 면접 답변(말버릇·잡음·빠른 말), 브라우저에서 녹음 → 업로드 → 전사 화면 흐름, 다른 노트북(코어 수·RAM이 적은 환경), `small` 이상 모델의 속도·메모리는 시험하지 않음.

### 카메라 자세 분석 수동 검증 항목 (실제 웹캠, 미실행)

1. `npm run dev`(localhost) 면접 화면에서 `동의하고 카메라 켜기` → 권한 허용 → 미리보기가 좌우 반전으로 보이고 "얼굴이 화면 안에 있어요"가 뜨는지. 첫 로딩 시간(모델·WASM 내려받기)을 적는다.
2. 개발자 도구 Network: 모델(`storage.googleapis.com`)과 앱 에셋 외에 영상·이미지 업로드가 없는지, API 요청 본문에 분석 수치가 없는지. MediaPipe 지표 전송 요청이 있으면 주소를 기록한다.
3. 정면 30초 답변 → 검출 비율 95% 이상, 벗어난 시간 거의 0, 좌우·숙임 0%에 가까운지.
4. 답변 중 의자에서 비켜 5초 이상 화면 밖 → 벗어난 시간 약 5초, 1초 이상 벗어난 횟수 1번.
5. 고개를 옆으로 약 20°, 30°, 45° 돌려 각각 몇 초 유지 → 어느 각도부터 '좌우 회전'에 잡히는지 기록하고 `YAW_THRESHOLD` 조정 여부 결정. 숙임(`PITCH_THRESHOLD`)도 같은 방식. 안경·조명이 어두운 경우도 한 번.
6. 녹음 답변 + 카메라를 함께 켜 마이크 레벨·녹음 저장·전사가 정상인지(마이크와 카메라는 별도 스트림).
7. `카메라 끄기`, 회고로 이동, 다른 메뉴로 이동, 탭 닫기 각각에서 브라우저의 카메라 사용 표시등이 꺼지는지.
8. 권한 거부·카메라를 다른 앱이 사용 중·답변 중 USB 카메라 분리 → 안내 문구가 뜨고 면접은 계속되는지.
9. 노트북 CPU 사용률(작업 관리자)을 카메라 끔/켬으로 비교. GPU 위임이 실패해 CPU로 돌 때도 확인.
10. 모바일(Android Chrome, iOS Safari)에서 HTTPS 배포본으로 1~3, 7 확인. 회고 표가 390px 폭에서 읽히는지.
11. 배포 주소에서 `vision_wasm_internal.wasm`이 `application/wasm`으로 내려오는지(아니면 느린 경로로 동작하거나 실패).

## 보안 검토 필요

- **React Router 취약점(2026-10-28 `npm audit`):** 설치본 `react-router-dom@6.30.6`·`react-router@6.30.6`(package.json `^6.28.0`)이 두 권고의 영향 범위(6.0.0~7.17.0)에 들어 Moderate 2건으로 보고됨. 수정 버전은 7.18.0 이상이고 `npm audit fix --force`는 7.x 메이저 업그레이드(호환성 깨짐)라서 실행하지 않았음. 이전 리뷰(P2-8)의 "영향 없음" 판단은 틀렸으므로 이 기록으로 대체함.
  - GHSA-337j-9hxr-rhxg(SSR 하이드레이션의 `deserializeErrors()`): 이 앱은 `BrowserRouter` 기반 Declarative Mode(`web/src/main.tsx`)이고 SSR을 쓰지 않으므로 해당하지 않는 것으로 판단.
  - GHSA-wrjc-x8rr-h8h6(`<Link>`·`useNavigate`의 백슬래시 오픈 리다이렉트): SSR과 무관하므로 위 판단으로 배제되지 않음. 코드 검색(grep) 기준으로 `Link`/`nav()`에 넘기는 값은 고정 경로와 서버가 준 id뿐이고 URL 쿼리 등 사용자 입력을 경로로 넘기는 곳은 찾지 못했음. 정식 검토와 7.x 업그레이드 여부는 결정 전.

## 미해결 문제

- e2e를 실행하면 추적 중인 `docs/screenshots/coaching-review-{desktop,mobile}.png`를 덮어씀(`web/e2e/coaching.spec.ts:70`). 지금은 AGENTS.md의 백업·복원 절차로 대응. **추후 테스트 수정 필요:** 스크린샷 경로를 환경 변수로 받거나 기본값을 `test-results/`로 바꾸고, 문서용 갱신은 명시적으로 켤 때만 하도록.
- e2e 설정은 PATH의 `python`을 씀. venv를 PATH에 넣지 않으면 백엔드가 뜨지 않음.
- 이 머신의 Playwright 브라우저는 2026-10-30에 v1248로 다시 받았지만 시스템 라이브러리(`libnspr4`·`libnss3`·`libasound2t64`)가 없어 `LD_LIBRARY_PATH`로 임시 지정해야 뜸. 근본 해결은 `sudo npx playwright install-deps chromium`.
- 로컬 STT 실패 사유(무음·바쁨·모델 실패 등)는 답변마다 저장하지 않아 화면은 "인식하지 못했거나 전사 요청이 실패했어요"로만 알림(서버 로그와 `/health`의 `stt.error`에는 남음). 사유별 안내가 필요하면 DB 컬럼 추가(스키마 변경 3곳)가 필요함.
- 로컬 STT는 동기 라우트 안에서 돎. 첫 전사 때 모델을 내려받으면 그 요청이 다운로드 시간만큼 걸림(미리 `python -m app.stt download` 권장).
- 앱 로거(`app.stt`)의 INFO 로그(모델 로딩·전사 시간)는 uvicorn 기본 설정에서 출력되지 않음. WARNING만 보임.
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
