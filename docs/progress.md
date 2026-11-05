# 진행 상태

최종 갱신: 2026-11-06. 갱신할 때는 날짜와 근거(명령·커밋)를 함께 적고, 오래된 항목은 지우거나 "완료"로 옮깁니다. 아래에서 "구현 사실", "자동 테스트", "외부 서비스 실검증"을 구분해 적습니다.

## 현재 브랜치 상태

- **Practice·Track 실사용 안정화(2026-11-06, `codex/practical-validation`):** 원격 main `e7e7967` 기준. 검증 소스 `9a9e526`을 정상 Push하고 [PR #6](https://github.com/leejw0010/Jobseeker/pull/6)을 생성했다(OPEN·미병합·자동 병합 없음). 작업 위치 `/home/user/projects/Jobseeker/.worktrees/practical-validation`; 이전 `/tmp` 소스는 작업 기록에서 복구·독립 대조 후 새로 검증했다. 원본 실행기·문서8개 SHA-256 일치, 실제 사용자 DB·녹음·비밀 설정 접근 없음. main 병합·팀 저장소 변경 없음. [기능별 결과·한계](validation/2026-11-06-usability-results.md), [파일별 팀 이식](integration/team-repository-handoff.md).
  - **최종 자동 검증:** Backend **388 passed36.37s**, build **85modules3.00s**, unit **132 passed4.0s**, 전체 E2E **107 passed/33skipped234.369s**, unexpected0/flaky0. desktop70·mobile37통과; mobile기존제외33(camera lifecycle3/Gaze5/recorder4/popup5/Track경합16). 단위 테스트와 E2E는 합산하지 않는다. 실제 Track등록→3문항/버전비교/복원/제출확인→전형편집·삭제/통계→Practice고정 자료를 두viewport에서 검증했다.
  - **실제 격리 DB:** PostgreSQL16.15/PostgREST16.5 **17 passed36.18s**. JWT A/B의 API 소유권과 비권한 RLS, 신규/기존/반복 migration, 활성화→off→on, 독립 트랜잭션 동시 저장, 버전 불변성·명시적 부모 삭제를 검증했다. 실제 Supabase 클라우드 Auth/Storage/RLS 확인으로 표현하지 않는다.
  - **수정:** append-only 제출 확인·복원 새초안, sticky수동/legacy상태와 날짜순 이벤트재계산·통계 분모·지원일미상, 상세응답 경합, 전사/대화 전체 지문·초안/저장후 코칭 무효화, 질문별 접근성. 전체 E2E에서 발견한 다른 지원 건 질문 혼입·생성/삭제 중첩과 옛 별점 역할selector도 실패 회귀→수정→통과했다. 타임아웃 증가/기능 제거 없음. 독립 전체/부분 재리뷰의 남은 Critical/Important 없음.
  - **미디어·비용:** 공개음성2개×3회 cachedWhisper오류0/RSS404.01MiB, 공개portrait 실제MediaPipe24회·2cleanup, 실제AudioContext합성/얼굴 **2passed25.2s**, Gaze invalid/abort **1passed5.7s**. 최신gatedPCM도sampling_gap으로 수치보류이며 실패complete를 비교 분모에 남겼다. 익명7시도/6그룹 JSON·CSV·Markdown 생성. 실제사람/장치정확도·Gaze3fresh측정·유료AI품질미검증. 로컬HTTP AI전송 **2passed8.3s**, 각시나리오coach2/debrief1/generate0; 외부유료API **0회**. pilot8013/5181 기동200/200과소유프로세스종료확인(장치접근없음).
  - **배포/후속:** 인증기본활성, 운영우회거부, HS256/JWKS와host토큰adapter. Track의새migration2개는분류off와별개필수전제, 분류활성화에는기존20261104+새practice_integrity필요. 실제DB적용없음. 팀 최신 `ec7b279`의 `profiles.archive` 변경·기존데이터전환미확인과React19/Router8/Vite8 차이를문서화. 팀frontend유지. G1/G2제품비활성. 남은작은한계: 다른탭의문항삭제는전체새로고침필요. 추적스크린샷·기존migration변경없음. Chromium은현재도LD_LIBRARY_PATH가필요하다(libnspr4/NSS/ALSA미탐지).
- **Stage 2 + 통합 코칭 개발(2026-11-04):** 최신 원격 main **de86b80**에서 `/tmp/Jobseeker-coaching`, `codex/stage2-multimodal-coaching`을 생성함. 기존 원본·통합·Review·main 검증 Worktree와 미커밋 실행기 9개 파일은 보존하며, 실제 사용자 녹음·개발 DB·비밀 설정을 읽거나 복사하지 않음. [설계](superpowers/specs/2026-11-04-integrated-coaching-design.md), [구현 계획](superpowers/plans/2026-11-04-integrated-coaching.md), [수동 배포/롤백](practice-insights-rollout.md).
  - 기준 검증: pytest **290 passed in 23.94s**, 웹 unit **68 passed (6.6s)**. 최종 소스 검증은 기능 커밋 **3005c48** 기준 아래와 같으며, GitHub 병합 커밋·병합 후 main 재검증 결과는 이 브랜치 PR 본문에 별도로 기록한다.
  - 구현 방향: category·기존 코칭 기준 세 개·R1 유지, 질문 유형/역량과 고정 스냅샷, 선택적 실제 인용 관찰, 기존 디브리프와 브라우저 수치에 근거한 통합 코칭. 전달 수치는 현재 탭 메모리에만 두며 서버/LLM으로 보내지 않는다. 새 스키마 매핑은 기본 비활성화이고 운영 SQL은 수동 적용한다.
  - 회귀 확인: 오디오 분석 초기화 예외가 녹음 시작까지 막는 기존 결함을 **de86b80 임시 사본**에서 재현(새 E2E가 녹음 표시 대기 실패), 분석 실패와 녹음 저장을 분리함. E2E 데이터 격리는 canonical 경로 검사로 `/tmp`의 외부 폴더 심볼릭 링크를 거부하며, PID 재사용 시에도 DB가 섞이지 않도록 실행별 새 디렉터리를 사용한다.
  - **최종 자동 검증:** `cd backend && .venv/bin/python -m pytest -q` → **332 passed in 28.46s**. `cd web && npm run build` → 타입 검사·Vite 빌드 통과(**80 modules, 2.53s**). `npm run test:unit -- --output=/tmp/jobseeker-coaching-unit-final` → **105 passed (4.9s)**. 전체 `npm run test:e2e` → **58 passed, 16 skipped (3.0m)**, JSON 기준 **181.793초**, unexpected0/flaky0. desktop37개 통과, mobile21개 통과·16개 의도적 건너뜀(Gaze5·Recorder4·Track4·Camera lifecycle3). 계산·확장 테스트는 105개 단위 테스트에만 포함한다.
  - 검증 환경: 새 임시 SQLite·실행별 새 canonical 녹음 디렉터리·8011/5179 전용 서버, 외부 키 비움·STT off·가짜 얼굴 검출기. Chromium 시스템 라이브러리는 기존 `LD_LIBRARY_PATH=$HOME/.cache/playwright-syslibs/root/usr/lib/x86_64-linux-gnu`를 사용했다. 한글 글꼴 패키지는 /tmp에만 풀고 테스트 FONTCONFIG_FILE로 지정했으며, 시스템/프로젝트 의존성에 설치하지 않았다. desktop/mobile 밝게·어둡게 캡처에서 한글 배치 확인, 가로 넘침0·키보드 링크·새 패널 및 실제 영상 표의 일반 글자 대비4.5:1 이상을 검사했다. 추적 문서 스크린샷 변경 없음.
  - 독립 리뷰 보완: legacy 디브리프를 숨기지 않고 미검증 보관 원문으로 분리, 분류 롤백 시 코어 코칭 유지, 전사문 수정 후 R1·개별 카드·새 음성 패널까지 속도 해석 무효화, 녹음 revision과 전사문을 함께 묶는 지문으로 기능 토글 뒤 재사용 방지. 명시적 글 답변은 기존 STT 상태를 바꾸지 않고 남은 선택 지문만 존재 확인 후 무효화한다. 마이그레이션 없는 스키마의 실제 별도 프로세스 API도 검사했다. 선택적 역량 관찰은 요구 태그 밖의 유효 사전 key를 별도 표시하고 알 수 없는 key/없는 인용/오래된 해시는 제외한다. 마지막 범위 재검토에서 남은 차단 결함 없음.
  - 테스트 실행 중 발견한 실패를 숨기지 않았다. 동시 unit/E2E의 결과 폴더 충돌은 출력 분리로 해결했다. 새 녹음 회귀는 free-mode의 초기 제한시간30을 실제 경과시간으로 받아들여 즉시 종료하던 테스트 조건을 수정했고, 원래 가짜 마이크/실제 인코더로 **5회 모두 통과(20.1s)** 후 전체 실행도 통과했다. 타임아웃 증가·기능 제거·검증 생략 없음. 기존 gaze 좌표 간헐 오류는 최종 전체 실행에서 재현되지 않았다.
  - 비용/요청 실측: 개발 Vite StrictMode의 분류 편집→회고→기록 흐름에서 홈 taxonomy GET2·질문 GET5(편집 새로고침 포함)·기록 taxonomy GET2였다. 회고/개선 틀을 열며 추가한 coach/debrief POST는 **0**. 가짜 코칭 응답 테스트의 선택적 관찰은 기존 호출1회 안에서 처리했다. 실제 유료 API 호출은 없었으며, 선택적 관찰을 켜면 토큰 길이는 늘 수 있다. 운영 빌드의 요청 수·실제 비용은 별도 실측하지 않았다.
  - 사용자 데이터: 원본 실행기·D-28·로컬 실행 문서9개 SHA-256 일치. 사용자 녹음·개발 DB·비밀 .env 열람/복사/수정/삭제와 운영 Supabase SQL 적용 없음. 새 마이그레이션·매핑과 선택적 AI 관찰은 기본 비활성화다. 실제 Supabase/Postgres/RLS/Storage/JWT·외부 AI 품질·실제 마이크/웹캠 정확도는 자동 테스트 결과와 구분한다.
  - 시선: 기존 실측 실패를 성공으로 바꾸어 보고하지 않는다. 비유한 값·눈 감김·해상도 변경 및 분석 제외 사유의 진단과 [사람이 수행할 3회 프로토콜](research/2026-11-04-gaze-protocol.md)을 추가하며 G1/G2는 개발용으로만 유지한다.
- **GitHub 반영 재개(2026-11-04):** 사용자 CLI 인증 복구 후 `leejw0010`의 저장소 쓰기 권한·merge commit 허용과 필수 정책 없음(현재 branch rules 빈 목록)을 확인함. 검증한 **e5fad9c**를 정상 push했고, [PR #3](https://github.com/leejw0010/Jobseeker/pull/3)은 **93b0ee9** merge commit으로 병합함. main과 P0 소스트리가 같음을 확인한 뒤 [통합 PR #4](https://github.com/leejw0010/Jobseeker/pull/4)를 생성함. 최종 원격 main 커밋·병합 후 전체 테스트의 기록 위치는 **PR #4 본문**이다. 아래 인증 실패 항목은 복구 전 실행 기록이며 현재 차단 상태가 아님. 사용자 원본 작업은 계속 보존하고 force push·rebase·브랜치 삭제·운영 DB 변경은 하지 않음.
- **인증 복구 전 main 반영 준비 기록(2026-11-04, `feature/integration-review-architecture`, `519505b` 이후 수정):** 사용자가 PR #3와 통합 PR의 commit·push·merge를 승인함. 원격 main은 **7db4f5b**, PR #3은 **95ad7c4**, Open·미병합·mergeable=true로 재조회함. 현재 GitHub 앱 권한은 pull:true/push:false이며, 실제 백업 ref 생성 요청은 **403 Resource not accessible by integration**, Git push 인증 확인은 **128 could not read Username, terminal prompts disabled**로 실패함. 보호 정책 상세 조회도403이라 정책을 추정하거나 우회하지 않음. 원격 브랜치 생성·PR 생성·병합은 하지 못한 상태다.
  - 코드 수정: 느린 저장소 삭제가 새 녹음 경로·보관 기한·삭제 시각을 덮던 경합을 경로 조건부 UPDATE로 방지. 사용자 전체 삭제는 cutoff 뒤 녹음을 선택하지 않고, 목록 시각이 누락·오래된 경우에도 현재 답변에 연결된 파일을 다시 확인해 보호함. 실패한 동일 파일을 두 번 세지 않음.
  - 카메라: 모델 로딩/권한 응답과 별개로 도착한 자원을 즉시 소유·정리. 화면 이탈·시작 실패 후 늦게 도착한 스트림/검출기도 닫음. 카메라 표본 수집 시작 조건과 Gaze 개발 전용 제한은 유지함.
  - 테스트 보완: extension session/sync 대역을 분리해 토큰이 sync에 저장되면 실패하도록 함. Track 동시 sync 테스트는 실제 첫 조회 누락→고유 제약→재조회 경로와 정확한 버전 이력을 검사함. 의도적 결함을 넣은 /tmp 사본에서 이전 테스트는 통과·개선 테스트는 실패함을 확인함.
  - PR #3 실제 HEAD 별도 검증: /tmp 임시 checkout에서 pytest **136 passed in 13.00s**, build 통과(Vite **2.25s**), desktop/mobile E2E **10 passed (48.2s)**. 해당 HEAD에는 unit 명령이 없음. pytest는 임시 DB·녹음 설정을 사용했고, E2E의 고정 녹음 경로도 새 /tmp checkout 내부에만 있음.
  - 최종 통합 검증: pytest **290 passed in 62.91s**, build 통과(Vite **4.38s**), unit **68 passed (12.7s)**. 전체 E2E **47 passed, 15 skipped (3.8m)**, JSON 기준 **229.512초**, unexpected0·flaky0. desktop31개 통과, mobile16개 통과·15개 건너뜀(Gaze5·Recorder3·Track4·새 카메라 수명3). 이는 로컬 통합 브랜치 검증이며, 원격 main 병합 후 검증은 인증 차단으로 아직 하지 못함.
  - 독립 최종 리뷰의 추가 지적(목록 시각 누락/오래된 경우의 연결 파일 보호)도 회귀 테스트 실패→수정→통과로 해결함. 새 녹음 회귀9개, 카메라 수명 회귀3개를 추가했고 타임아웃 증가·기능/검증 제거는 없음. 프로덕션 JS 산출물3개에서 GazeLab 경로·실험실 화면 문자열이 없음을 확인함.
  - `npm audit --omit=dev --json` 재조회: **moderate2, high0, critical0**, exit1. react-router/react-router-dom의 기존 GHSA-wrjc-x8rr-h8h6·GHSA-337j-9hxr-rhxg이며 수정 제안은 react-router-dom7.18.5(메이저 업그레이드)다. 의존성은 이번 변경에서 바꾸지 않았고 기존 보안 검토 과제로 유지한다. 아래 보안 검토 절 참고.
  - 원본 실행기·D-28·문서 미커밋 작업9개는 해시로 보존 확인. 사용자 녹음/비밀 설정/개발 DB를 읽거나 복사하지 않았고, 실제 Supabase/OpenAI 호출·마이그레이션은 없음. 임시 테스트 서버와 임시 저장소만 사용함.
  - 다음 실행: GitHub 쓰기 인증을 해결한 후 통합 브랜치 push → 검증한 head와 정책 재확인 → PR #3 merge commit → 통합 PR 하나(main 대상으로, Architecture·STT·Video·개발 전용 Gaze·Review 포함) 생성/병합 → 별도 main Worktree에서 전체 검증. 원본 SHA 보존, force push·rebase 없음. [수행 계획](superpowers/plans/2026-11-04-main-integration.md).
- `feature/integration-review-architecture`(2026-11-03, `/home/user/projects/Jobseeker-integration`): `feature/architecture-fixes` **59d7470**을 기준으로 `feature/review-insights` **1774030**을 병합. 공통 조상 **eaa8477**, Architecture 고유 커밋 5개·Review 고유 커밋 1개를 보존. `docs/progress.md` 두 충돌 구간은 Architecture의 단위 테스트 경로·스크린샷 격리와 Review의 녹음 답변 검증·기존 gaze 이슈를 함께 반영. `web/e2e/review-insights.spec.ts`는 자동 병합(공통 API 주소 import와 Stage 1 기본 대기시간 복원 모두 유지).
  - 원본 `/home/user/projects/Jobseeker`의 `Start-JobSeeker.cmd`, `scripts/`, D-28·로컬 실행기 문서 변경은 별도 세션 작업으로 남김. 통합 Worktree로 가져오거나 수정하지 않음.
  - 통합 전 Architecture 기준: pytest **281 passed in 32.67s**, build 통과, 단위 테스트 **68 passed (18.3s)**. 통합 후: pytest **281 passed in 34.01s**, build 통과(Vite **5.08s**), 단위 테스트 **68 passed (16.2s)**. 전체 브라우저 결과는 아래 통합 검증 절에서 별도로 집계.
  - Stage 2·시선 Phase 1 개발, 실제 Supabase/OpenAI 호출, push·PR 생성·main 병합은 하지 않음.
- `feature/architecture-fixes`(2026-11-03 원본 브랜치 HEAD **59d7470**, `feature/review-insights` eaa8477에서 갈라짐): 외부 아키텍처 분석 보고서(2026-11-03)의 지적을 코드로 확인한 뒤 고친 작업. 사용자 요청으로 Codex가 진행 중 작업물을 `49aceee`·`a8fcea3`·`cd8fc53`·`f4e3212`로 커밋함. `git push -u origin feature/architecture-fixes`는 `could not read Username for 'https://github.com': No such device or address`로 실패했고, 연결된 GitHub 앱도 저장소 권한이 `push: false`라 업로드하지 못했음. 그 뒤의 확장·문서 변경은 `59d7470`에 커밋돼 있으며, 통합에는 이 커밋까지 포함함.
  - 고친 것: e2e 녹음 폴더 격리(P0), 마이크 늦은 권한 응답·중복 요청, 같은 답변 동시 업로드, Track URL 고유성·버전 번호 경합·PATCH null, 자소서 저장 중 입력 보존, 목록 응답 역전, 실패 처리·재진입, 별점 재진입, `debrief → router` 역방향 의존 제거(`app/services/`), 저장소 오류 분류, 질문 생성 응답 검증, 카메라 비전송 검사 주소, 미분석 공백의 미검출 구간 병합, STT 보고서 세트 선택, 설정 검증·JWT 경로 강화, 확장 토큰 연결 지점·주소 권한 경고, 열거값 대조, 의존성 분리·버전 기록, 계산 테스트 분리, 정리 테스트 DB 격리, SQLite 외래 키. 결정은 [decisions.md](decisions.md) D-23~D-27.
  - 자동 검증(2026-11-03, 마지막 변경 뒤 직접 실행): `cd backend && .venv/bin/python -m pytest -q` → **281 passed in 21.12s**; `cd web && npm run build` → 통과; `npm run test:unit` → **68 passed (6.4s)**; `LD_LIBRARY_PATH=$HOME/.cache/playwright-syslibs/root/usr/lib/x86_64-linux-gnu PATH=../backend/.venv/bin:$PATH npm run test:e2e` → **34 passed, 12 skipped (3.6m)**(Architecture 단독 결과, 통합 전체 검증으로 사용하지 않음), 실패 없음(desktop `camera.spec.ts` 포함). 스크린샷은 AGENTS.md 절차로 백업·복원했고 실행 전후 `git status -- docs/screenshots/` 변경 없음. 새 테스트는 고치기 전 코드에서 먼저 실패하는 것을 확인함(동시 업로드는 "먼저 시작한 녹음" 전사문이 두 번째 녹음 파일과 짝지어짐, PATCH null은 `IntegrityError`, 공유 DB의 만료 정리는 다른 테스트 녹음 16개를 함께 지움 등).
  - 앞선 Codex 실행의 e2e **27 failed, 5 skipped**는 전부 브라우저 시작 단계의 `libnspr4.so` 없음이었음(위 `LD_LIBRARY_PATH` 없이 실행). 화면 흐름 실패가 아님.
  - 실제 외부 서비스(OpenAI·Supabase) 검증은 하지 않음. 새 URL 고유 인덱스·행 잠금·JWT 경로는 SQLite와 pytest로만 확인했고 실제 Postgres·Supabase에서는 확인하지 않음.
- `main`: PR #1(확장 팝업)과 PR #2(`codex/evidence-interview-coach`, 제출본 기반 면접 코칭)까지 머지됨.
- `feature/practice-p0`: 2026-11-03 로컬 브랜치는 없고 원격 추적 ref `origin/feature/practice-p0`는 **95ad7c4**. 아래 PR #3의 **1a12453**은 2026-10-28 당시 조회 기록이며 현재 원격 상태로 재검증하지 않음. 현재 로컬 계보는 `origin/main` → `origin/feature/practice-p0` → `feature/video-analysis` → `feature/local-stt` → `feature/gaze-calibration` → `feature/review-insights` 순으로 조상 관계를 확인함.
- **PR #3:** https://github.com/leejw0010/Jobseeker/pull/3 · `feature/practice-p0` → `main` · 2026-10-28 GitHub API(`GET /repos/leejw0010/Jobseeker/pulls/3`)로 확인한 당시 **Open, 미병합, draft 아님**, head 1a12453. (`gh`는 설치돼 있지 않음.)
- `feature/local-stt`(2026-11-01 로컬 커밋 3개: 로컬 STT, D 카메라 지표, A 평가 도구): `feature/video-analysis`(56e28ac, `main` 미병합)에서 갈라짐. push·PR 전. 이어지는 시선 분석(G)은 이 위에서 만든 `feature/gaze-calibration`에서 함.
- `feature/gaze-calibration`(2026-11-01): `feature/local-stt`(9e4cc16)에서 갈라짐. G 설계·계획 커밋 뒤 0단계(개발 전용 시선 실험실과 계산 모듈)만 구현, 실제 웹캠 시험 대기. push·PR 전.
- `feature/review-insights`(2026-11-03): `feature/gaze-calibration`(56548ad)에서 갈라짐. 회고 한눈에 보기(R1)만 구현. 백엔드·API·DB 변경 없음. push·PR 전.
- 추적하지 않는 파일: `.vscode/`(개인 설정). `backend/.venv/`는 2026-10-28에 `.gitignore`에 추가함.

## 1. 구현 사실 (코드로 확인)

| 기능 | 위치 |
|---|---|
| Practice: 질문은행·맞춤 질문·모의시험·녹음/글 답변·전사·회고 | `routers/practice.py`, `web/src/pages/Session*.tsx` |
| 제출본 기반 코칭, 인용 대조, 꼬리질문(1회), 다시 연습 | `app/coaching.py`, `app/llm.py:verify_quote` |
| P0: 녹음 동의(403), 전사 후 원본 삭제, 보관 기한·만료·고아 파일 정리, 동의 철회, 설정 화면 | `app/retention.py`, `web/src/components/ConsentPanel.tsx`, `web/src/pages/PracticeSettings.tsx` |
| P0: 자동 디브리프(heartbeat, 중복 작업 방지, 실패 재시도), 자기평가 기반 다시 연습 | `app/debrief.py` |
| Track: 지원 건·단계·버전·복원·sync·통계 | `routers/track.py` |
| 카메라 자세 분석(선택, 브라우저 전용·메모리 보관): 답변·분석 시간, 얼굴 검출 비율, 찾지 못한 시간(`none`), 일부 프레임 밖 시간(`edge`), 고개 좌우·숙임 상대 변화. 2026-10-30 지표 분리(D, `feature/local-stt` 미커밋, [설계](superpowers/specs/2026-10-30-d-camera-metrics-design.md)) | `web/src/video/`, `web/src/components/useFaceAnalysis.ts`·`CameraPanel.tsx`·`VideoReportCard.tsx` (브랜치 `feature/video-analysis`, 미커밋) |
| 로컬 STT(`STT_PROVIDER=local` 기본, faster-whisper `base`·CPU·INT8, 지연 로딩·재사용·캐시 우선, 한 번에 하나), LLM 키와 분리된 `/health`의 `stt` | `app/stt.py`, `web/src/sttText.ts` (브랜치 `feature/local-stt`, 미커밋) |
| 시선 분석 0단계(개발 전용 실험실 `/dev/gaze-lab`): 특징 추출, G2 화면 좌표 릿지 회귀(묶음 교차 검증), G1 렌즈 응시 분류기(별도 응시로 평가), 표본 주기 측정, D 250ms 격자. 면접 화면·회고에는 아직 없음 | `web/src/video/gaze/`, `web/src/pages/GazeLab.tsx` (브랜치 `feature/gaze-calibration`) |
| 회고 한눈에 보기(R1): 코칭 상태 격자, 답변 시간·말 빠르기(분당 음절, 녹음 길이 기준)·자기평가 막대와 표 보기, 규칙 기반 보완점(최대 5개, 답변 카드 링크). 세션 응답 값만 쓰고 LLM 호출 없음 | `web/src/review/insights.ts`, `web/src/components/ReviewInsights.tsx` (브랜치 `feature/review-insights`) |
| Track: 자소서 버전 단어 단위 diff | 프런트엔드 `web/src/components/Diff.tsx`(백엔드에는 diff 로직 없음) |
| 인증: JWT(HS256) 검증 후 uuid `sub`만 사용(없거나 형식이 다르면 401), 라우터에서 `user_id` 필터. 시작 시 설정 검증(`Settings.check`) | `app/auth.py`, `app/config.py`, `routers/*` ([architecture.md](architecture.md) "인증과 데이터 접근 경계") |
| 공용 업무 처리: 답변 점검(`answer_coaching`), 자소서 버전 번호(`track_versions`) | `app/services/` (2026-11-03) |

## 2. 자동 테스트 (외부 서비스 없이)

| 대상 | 테스트 | 검사하는 것 / 검사하지 않는 것 |
|---|---|---|
| 코칭·인용 대조·꼬리질문·다시 연습 | `test_interview_coaching.py`, e2e 시나리오 1 | OpenAI는 모의 응답 |
| 녹음 동의·원본 삭제·만료·고아 파일·동의 철회 API | `test_privacy.py` | 서버 동작. 설정 화면 UI는 e2e가 열지 않음 |
| 녹음 동의 화면(`ConsentPanel`) | e2e 시나리오 2·4·5(동의 없는 상태로 시작해 `동의하고 시작` 버튼을 눌러 녹음 시작) | 동의 패널이 뜨고 동의 후 녹음이 시작되는 것 |
| 자동 디브리프·다시 연습 | `test_debrief.py`, e2e 시나리오 1 | e2e는 키 없는 모드에서 디브리프가 남은 답변을 기본 점검하는 것과 작업 종료(`debrief_running`)만 확인. AI 요약 카드는 e2e 대상 아님 |
| STT 요청 형식·재시도·오류 처리 | `test_transcription.py`, e2e 시나리오 5 | 모의 응답. 실제 인식 정확도는 아님 |
| 로컬 STT | `test_local_stt.py`(25개) | 가짜 모델 + PyAV로 만든 실제 WebM/Opus. 키 없이 전사·원본 삭제, 지연 로딩 1회·재사용·동시 첫 요청 1회 로딩, 캐시 우선·다운로드 1회, 다운로드/로딩 실패 후 재시도, 라이브러리 import 실패(500이 아니라 `failed`), 무음·깨진 파일·너무 긴 녹음·바쁨·모델 오류, 한 번에 하나 실행, 동의 403, 보관→수정→기본 코칭→녹음 삭제, `off`·미설치, `/health` 분리. **인식 정확도는 검사하지 않음.** e2e는 `STT_PROVIDER=off`로 돌려 로컬 전사를 열지 않음 |
| 시선 분석 0단계 | `web/tests/unit/gaze-math.spec.ts`(계산), `gaze-lab.spec.ts`(실험실 흐름 5개) | 합성 얼굴과 가짜 검출기. 누출 없는 묶음 교차 검증, 보수적 렌즈 임계값·분포 밖 unknown, 오차보다 작은 영역은 판정 안 함, NaN 없는 실패, 창 크기 변경 무효화, 전송 없음, 프로덕션 번들 제외. **실제 정확도는 검사하지 않음** |
| 회고 한눈에 보기 | `web/tests/unit/review-insights-math.spec.ts`(계산 11개), `review-insights.spec.ts`(글 답변 화면 2개), `review-insights-recorded.spec.ts`(녹음 답변 화면 5개). 화면 테스트는 desktop·mobile 모두 | 계산: 음절 수, 말 빠르기 조건(녹음·전사·5초), 세션 평균 3개 이상일 때만 빠름·느림, 모의시험만 시간 규칙, 역할 규칙, 코칭 보완 묶음과 전사문에 있는 인용만 표시, 우선순위, 5개 제한, NaN 없음. 화면: 글 답변 세션의 격자·이유 문장·가로 넘침 없음. 녹음 답변 모의시험 세션(가짜 녹음 바이트를 API로 올리고 녹음 길이를 지정, 카메라·마이크 없음)에서 답변 시간·말 빠르기·자기평가 막대의 값과 너비, 제한·평균 선 위치, 표 보기 값, 코칭 격자, 보완점 순서·근거·접기, 보완점 링크를 누르면 해당 답변 카드로 이동, 키보드(Tab 순서·Enter로 표 보기와 링크), 카드 글자 대비 4.5:1(밝게·어둡게). 기대값은 구현과 따로 손으로 계산. 기준값이 실제로 도움이 되는지는 사용자 검증 전 |
| 잘못된 id → 404 | `test_malformed_ids.py` | |
| 스키마 | `test_migration.py` | **로컬 SQLite 업그레이드**와 **id 컬럼의 Postgres `UUID` 타입 컴파일**만 검사. Supabase SQL 실행·RLS·Storage 정책은 검사하지 않음 |
| 카메라 자세 분석 | e2e `camera.spec.ts`(가짜 검출기 + Chromium 가짜 카메라, 실제로 모은 API 요청이 있는지 먼저 확인), `web/tests/unit/video-metrics.spec.ts`(계산만, 브라우저 없이. 긴 미분석 공백은 `none` 구간을 끊음) | `none`/`edge` 시간이 겹치지 않음, 이마만 넘은 얼굴은 검출 100%·찾지 못한 시간 0, 답변·분석 시간(탭 가림·도중 종료·표본 없음), 넘은 쪽 문구의 좌우 반전, 미리보기 `contain`, 켜기·끄기·다시 켜기, 회고 수치 표시, 화면을 떠날 때 카메라 트랙 정리, 수치를 API로 보내지 않음, 새로고침하면 사라짐, 카메라 거부·모델 실패 시 기존 흐름 유지. **실제 MediaPipe 모델·실제 얼굴로는 검사하지 않음** |
| Track: 지원 건·단계·버전 중복 방지·복원·sync upsert·통계, URL 고유(409)·동시 sync·버전 번호 경합·PATCH null(422) | `test_track.py`, `test_migration.py`(인덱스·외래 키) | 백엔드 API만. 프런트엔드 단어 diff(`Diff.tsx`)는 pytest·e2e 모두 직접 검증하지 않음 |
| Track 화면 비동기 흐름 | e2e `track.spec.ts`(desktop 4개) | 저장 중 이어 쓴 자소서 보존, 되돌리기, 늦게 온 검색 응답 무시, 수정 실패 메시지·서버 값 유지. 단계 기록·문항 추가 실패는 같은 처리기를 쓰지만 따로 검사하지 않음 |
| 마이크 수명·별점 재진입 | e2e `recorder.spec.ts`(desktop 3개) | 화면을 떠난 뒤 온 마이크 권한 스트림을 닫음, 권한을 묻는 동안 두 번 시작해도 요청·녹음 한 번, 별점 저장 중 재전송 없음. 실제 브라우저 권한 창은 아님(`getUserMedia`를 붙잡아 흉내) |
| 설정·인증·계층·열거값 | `test_config.py`, `test_auth.py`, `test_architecture.py`, `test_enums.py` | 숫자 설정 오류·인증 설정 조합, JWT 만료·서명·aud·sub, 라우터 역방향 import 금지, 모델·스키마·SQL·types.ts 열거값 일치. 실제 Supabase JWT는 아님 |
| 확장 순수 함수 | `web/tests/unit/extension.spec.ts` | 공고 추정, 토큰 저장(`chrome.storage.session` 대역), 주소 권한 검사. 팝업 화면·Chrome 권한·페이지 주입은 아님 |
| 녹음 동시 업로드·저장소 오류 | `test_privacy.py` | 겹친 업로드는 나중에 시작한 녹음이 이김(409), 이전 파일은 연결 뒤 삭제·실패 시 다음 정리, 저장소 401·403·500·연결 실패는 502. 만료 정리 테스트는 `isolated_db`로 테스트 전용 DB |

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

`feature/review-insights`(회고 한눈에 보기) 직접 실행 결과:
- 2026-11-03 1차(커밋 eaa8477, 메모리 부족: 여유 44~300MB·스왑 1023/1024MB): pytest **219 passed**, `npm run build` 통과, 전체 e2e **81 passed, 3 failed, 62 skipped**(146개). 실패는 desktop `camera.spec.ts` 3개.
- 2026-11-03 안정화(별도 worktree `../Jobseeker-review-insights`, 메모리 여유 약 1.2~1.5GB): `npm run build` 통과, 전체 e2e **93 passed, 1 failed, 62 skipped**(156개 = 테스트 78개 × desktop·mobile, 3.1분). 실행 중 스왑 입출력 초당 8MB 이하.
  - 건너뜀 62개는 모두 mobile에서 의도적으로 건너뛰는 것: 계산 테스트(`gaze-math` 33, `video-metrics` 13, `review-insights-math` 11)와 desktop 전용 `gaze-lab` 5. 156개 모두 시작했고 중단·미실행은 없음.
  - 실패 1개는 `gaze-lab.spec.ts`의 "dots are drawn exactly where they are scored"(값 `NaN`). 같은 테스트만 5번 다시 돌리면 5번 모두 통과. 원인은 테스트의 경쟁 상태: 점을 찾는 단계와 위치를 재는 단계가 나뉘어 있는데, 실험실 화면이 점(`div`)과 렌즈 표시(`div`)를 같은 자리에서 그려 React가 같은 DOM 요소를 재사용하므로 그 사이에 다음 단계로 넘어가면 좌표 속성이 없는 렌즈 표시를 재게 됨. 앱 결함이 아니며 R1과 무관(G 0단계 테스트). 고치는 방법: 한 번의 `page.evaluate` 안에서 `.gaze-lab-dot[data-target-x]`를 찾고 바로 재기(미적용, 아래 미해결 문제).
  - 1차의 카메라 실패 3개는 메모리 부족 탓으로 판단: 메모리가 풀린 뒤 세 테스트만 3번씩 다시 돌리면 **9/9 통과**(38.7초), 전체 실행에서도 모두 통과. 1차 실패 때 trace에서 같은 세션 조회가 17ms → 3,028ms, 클릭이 1.3~6.1초 걸렸고, 실패 단계가 실행마다 달랐으며(미리보기·회고 제목·답변 끝내기), 브랜치 전 코드(56548ad)에서도 같은 오류가 났음. 값이 틀린 실패는 없었고 모두 시간 초과.
  - 회고 한눈에 보기 테스트에서 첫 화면만 20초 기다리던 설정을 지우고 기본 시간(5초)으로 통과함.
  - `backend/.venv/bin/python -m pytest -q` → **219 passed**(백엔드 변경 없음). 스크린샷은 AGENTS.md 절차로 백업·복원(실행 후 `docs/screenshots/` 변경 없음).
- 접근성·화면 확인(2026-11-03): 나눔 글꼴(`fonts-nanum`을 `apt-get download`로 받아 이 실행에만 `FONTCONFIG_FILE`로 지정)로 desktop·mobile, 밝게·어둡게 캡처해 한글 표시와 배치를 눈으로 확인(가로 넘침 0). 키보드로 격자 링크를 옮기면 초점 표시가 보이고, 표 보기는 Enter로 열림. 카드 안 보조 문장(`.muted`)이 밝은 화면에서 대비 3.41:1이라 카드 안에서만 `--text-2`(7.73:1)로 바꿈(테스트 추가).

### 통합 검증 (2026-11-03, 별도 Worktree)

- 실제 실행 환경: 기존 Python 3.12 venv 실행 파일을 사용하고, 웹 의존성은 통합 Worktree에 복사함(추가 설치·버전 변경 없음). 비밀 `.env`, 개발 DB, 사용자 녹음은 읽거나 복사하지 않음.
- E2E 사전 안전 검사: 실제 개발 녹음 경로를 `E2E_RECORDINGS_DIR`로 지정한 설정 로딩은 예상한 오류로 거부됨. 실제 실행은 심볼릭 링크가 아닌 새 빈 canonical `/tmp/jobseeker-integration-e2e-recordings-9zoyffjz`를 명시했고, `RECORDINGS_DIR`로 전달됨. DB는 `playwright.config.ts`의 실행 PID별 임시 SQLite이며, 서버는 `reuseExistingServer: false`로 새로 시작. 시작 직전 8011/5179 포트가 비었음을 확인함.
- 동의 철회는 해당 개발 사용자 폴더의 고아 파일까지 지우므로 DB 격리만으로는 부족함. 이번 실행은 저장소 루트도 새 임시 폴더로 격리하여 기존 녹음에 접근하지 않음. `UPDATE_DOC_SCREENSHOTS=0`으로 문서 스크린샷도 보호함.
- Chromium v1248은 기본 실행에서 `libnspr4.so`, `libnss3.so`, `libnssutil3.so`, `libasound.so.2`가 누락됨. `LD_LIBRARY_PATH=$HOME/.cache/playwright-syslibs/root/usr/lib/x86_64-linux-gnu`를 적용한 `ldd`에서는 누락 없음.
- 명령: `cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`, `cd web && npm run build`, `npm run test:unit`, `PATH=../backend/.venv/bin:$PATH LD_LIBRARY_PATH=$HOME/.cache/playwright-syslibs/root/usr/lib/x86_64-linux-gnu npm run test:e2e -- --reporter=line,json`(위 녹음 폴더·스크린샷 환경도 함께 지정, 외부 서비스 키는 비움).
- 전체 브라우저 실행: **44 passed, 12 skipped (3.1m)**, exit 0. JSON 보고서 기준 **184.498초**, unexpected 0·flaky 0. desktop **28 passed**, mobile **16 passed, 12 skipped**로 총 **56개**를 모두 집계. 건너뜀은 mobile의 desktop 전용 gaze-lab 5개·recorder 3개·Track 비동기 4개이며, mobile은 390×844 Chromium 뷰포트(실제 기기·Safari 아님). 녹음 답변 Review Insights 5개는 desktop/mobile 모두 통과했고, 기존 gaze 좌표 간헐 오류와 카메라 시간 초과는 이번 전체 실행에서 재현되지 않음. 이전 Stage 1의 **93 passed / 1 failed / 62 skipped**에는 현재 `web/tests/unit/`으로 옮긴 계산 테스트와 mobile 중복 skip이 포함돼 있으므로 통합 브라우저 수와 직접 비교하지 않음. 현재 계산·확장 단위 테스트는 별도 **68개**.
- 독립 읽기 전용 리뷰: 통합으로 생긴 Critical/Important/Minor 결함 없음. 양쪽 소스 변경 보존, 녹음 격리·단위 테스트 분리와 자동 병합 결과를 재확인함. 녹음·카메라·전사는 가짜 입력/비활성 경로이므로 실제 하드웨어 정확도나 코칭 기준의 유용성까지 입증하지 않음.
- 원본 미커밋 파일 9개의 SHA-256·Git 상태와 기존 모든 로컬/원격 추적 ref가 실행 전과 같음을 확인함. 사용자 녹음은 내용·목록을 읽지 않았으며, 테스트는 임시 저장소만 사용함. 문서 스크린샷 diff 없음. 테스트 서버 종료 후 8011/5179 포트 사용 가능 여부도 재확인함.
- **Stage 2 착수 판단:** 통합 코드와 자동 테스트 기준으로 착수 가능한 상태. 기존 gaze 테스트 경쟁 상태·앱 전체 접근성 과제는 남아 있고 실제 Supabase Postgres/RLS/Storage/JWT·OpenAI·실제 장치 검증은 별도다. 이 판단은 외부 서비스 배포 준비 완료를 뜻하지 않으며, 이번에는 Stage 2나 시선 Phase 1 코드를 작성하지 않음.
- **PR 후속:** 이 통합 브랜치의 로컬 병합 커밋을 검토한 뒤 사용자가 push하고 PR을 생성한다. 로컬 `origin/main`에는 앞선 기능 계보도 아직 없으므로, 기존 PR들의 실제 병합 상태와 PR base를 먼저 확인할 것(이번에는 fetch·push·PR 생성·main 병합을 하지 않음). 테스트 로그·E2E JSON은 `/tmp/jobseeker-integration-*.log`, `/tmp/jobseeker-integration-e2e-results.json`에 있음.
- 코드 확인과 자동 테스트 결과만 기록하며, 실제 Supabase Postgres/RLS/Storage/JWT 및 실제 OpenAI 품질 검증은 이번 작업에서 하지 않음.

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

### STT 정확도 평가 A — 2단계(P 전체) 실행 결과 (2026-10-30, **대부분 미완료**)

[설계](superpowers/specs/2026-10-30-a-stt-evaluation-design.md) · [실행 방법](stt-eval.md). 같은 환경(WSL2, i5-1135G7 8스레드, RAM 3.7GB, 스왑 1GB, 시작 때 스왑 여유 0MB·여유 메모리 1.7GB, 앱 개발 서버·VS Code 실행 중). 기본값은 바꾸지 않음(`base`).
- **완료된 측정은 `base-default` 1회뿐.** P 208개 클립(49.6분): CER_num 12.1%, CER_content 13.5%, 용어 재현율 47.0%(Claude가 뽑은 용어 목록 기준), 10글자 이상 빠뜨린 말 10분당 0.81, 무음 구간 지어낸 말 3건. 전체 실행 7.8분. 60초 녹음 4건의 1건 지연(모델 로딩 뒤 decode+전사) 중앙 4.3초·최대 6.4초, 120초 4건 중앙 10.9초·최대 13.3초(반복 없음, p95는 최댓값과 같음). 최대 RSS 442MB, 스왑 증가 0, PSI full 최대 2.9.
- **`small-default`는 23개 클립(Zeroth 낭독, 4.2분)에서 메모리 감시가 멈춤**: 스왑 증가 319MB(기준 256MB), 최소 여유 메모리 275MB, 프로세스 RSS 846MB. 이 23개만 짝 비교하면 CER_num base 10.1% → small 4.1%(차이 −5.9%p, 부트스트랩 95% −8.1~−3.8%p, 표본이 작고 낭독 음성뿐), 클립당 지연 중앙 1.6초 → 5.0초(약 3.1배, 클립 길이 중앙 10.8초).
- **나머지 24개 실행은 측정이 아님**: small 중단 직후의 PSI full 10초 평균(15~31)이 남아 있는 상태에서 다음 실행이 곧바로 시작돼 2초 만에 연달아 중단됨. 실행 사이에 메모리 압박이 가라앉기를 기다리는 단계가 배치 스크립트에 없었던 것이 원인(도구 문제, 평가 조건 아님).
- **30초 지연 보충 측정(L-30)은 만들지 못함**: 30초 안에 무음 9초를 넣으면 긴 발화 두 개가 들어가지 않아 클립 생성이 실패함(도구 문제).
- 2026-11-01 사용자 결정(D-20): 기본값 `base` 유지, `small` 평가는 하드웨어 한계로 미완료, 전체 재실행은 승인 전까지 하지 않음. 결과 요약: [research/stt-eval-2026-10-30.md](research/stt-eval-2026-10-30.md). 원본 측정값은 저장소 밖 `~/stt-eval-archive/2026-10-30/`(체크섬 포함)에 보관.
- 2026-11-01 도구 수정(승인됨): 실행 사이 자원 회복 대기(`wait_for_recovery`, 10분 안에 회복하지 않으면 `not_started`·배치 중지), L-30 클립을 통째 발화로만 구성하고 구성(말소리·무음 초)을 기록, 보고서에 실행 상태 분류(완료·자원 보호로 중단·자원 미회복으로 시작 안 함·프로그램·추론 오류)와 미완료 실행의 부분 결과를 따로 표시, 한 run-id에 P·S 섞기 거부. `test_stt_eval.py` 58개 통과(백엔드 전체 219개).
- 2026-11-01 작은 점검(전체 재실행 아님): `base-default`로 P 2개 + L-30 2개를 이어서 실행 → 두 실행 모두 `완료`, 시작 전 대기 27초·10초(앞 실행 뒤 10초 이상 잠잠해진 뒤 시작), 30초 클립 1건 지연 2.1·2.2초(2건, 벤치마크 수치 아님). L-30 8개: 모두 30.0초, 말소리 24.1~28.0초, 발화 2~4개, 자른 발화 없음.

## 3. 외부 서비스 실검증 (아직 안 함)

- OpenAI: 실제 키로 STT 정확도, 코칭·꼬리질문·디브리프 응답 품질, JSON 형식 준수를 확인하지 않음. 테스트는 모두 모의 응답이나 가짜 서버로 돌림.
- Supabase: 실제 프로젝트에서 `schema.sql`·마이그레이션 실행, RLS 적용 여부와 백엔드 접속 역할의 RLS 우회 여부, 백엔드 연결에서 `auth.uid()` 값, Storage 업로드·목록·삭제와 정책, JWT 인증을 확인하지 않음. 백엔드 Postgres 경로는 로컬 Postgres 16으로만 확인함(README 기록, RLS는 대상 아님).
- 확장: 실제 채용 사이트(사람인·원티드 등)에서 제목 추출을 시험하지 않음(테스트용 가짜 공고 페이지만).
- 카메라 자세 분석: 실제 웹캠·실제 MediaPipe 모델로 시험하지 않음. 아래 수동 검증 항목 참고.
- 로컬 STT: 실제 마이크로 녹음한 자연스러운 면접 답변(말버릇·잡음·빠른 말), 브라우저에서 녹음 → 업로드 → 전사 화면 흐름, 다른 노트북(코어 수·RAM이 적은 환경), `small` 이상 모델의 속도·메모리는 시험하지 않음.

### 카메라 자세 분석 수동 검증 항목 (실제 웹캠, 미실행)

1. `npm run dev`(localhost) 면접 화면에서 `동의하고 카메라 켜기` → 권한 허용 → 미리보기가 좌우 반전으로 보이고 "얼굴이 화면 안에 있어요"가 뜨는지. 첫 로딩 시간(모델·WASM 내려받기)을 적는다.
2. 개발자 도구 Network: 모델(`storage.googleapis.com`)과 앱 에셋 외에 영상·이미지 업로드가 없는지, API 요청 본문에 분석 수치가 없는지. MediaPipe 지표 전송 요청이 있으면 주소를 기록한다.
3. (2026-10-30 대체) 지표 점검은 아래 "카메라 지표 점검(D) 수동 절차"를 따른다.
4. (2026-10-30 대체) 위와 같음.
5. 고개를 옆으로 약 20°, 30°, 45° 돌려 각각 몇 초 유지 → 어느 각도부터 '좌우 회전'에 잡히는지 기록하고 `YAW_THRESHOLD` 조정 여부 결정. 숙임(`PITCH_THRESHOLD`)도 같은 방식. 안경·조명이 어두운 경우도 한 번.
6. 녹음 답변 + 카메라를 함께 켜 마이크 레벨·녹음 저장·전사가 정상인지(마이크와 카메라는 별도 스트림).
7. `카메라 끄기`, 회고로 이동, 다른 메뉴로 이동, 탭 닫기 각각에서 브라우저의 카메라 사용 표시등이 꺼지는지.
8. 권한 거부·카메라를 다른 앱이 사용 중·답변 중 USB 카메라 분리 → 안내 문구가 뜨고 면접은 계속되는지.
9. 노트북 CPU 사용률(작업 관리자)을 카메라 끔/켬으로 비교. GPU 위임이 실패해 CPU로 돌 때도 확인.
10. 모바일(Android Chrome, iOS Safari)에서 HTTPS 배포본으로 1~3, 7 확인. 회고 표가 390px 폭에서 읽히는지.
11. 배포 주소에서 `vision_wasm_internal.wasm`이 `application/wasm`으로 내려오는지(아니면 느린 경로로 동작하거나 실패).

### 카메라 지표 점검(D) 수동 절차 (실제 웹캠, 미실행)

목적: "얼굴이 화면 안에 있는데 이탈로 잡힌다"의 원인을 가린다(가설 H1 이마·턱 메시가 프레임을 넘음, H2 검출이 잠깐씩 끊김, H3 카메라 해상도가 4:3이 아님). 실행: `cd web && VITE_CAMERA_DEBUG=true npm run dev`(백엔드도 실행). 각 자세로 **30초 글 답변**(녹음 흐름도 한 번)을 한 뒤 회고 카드의 답변 시간·분석한 시간·검출·찾지 못한 시간·일부 프레임 밖과, 카메라 패널 진단(상태별 표본 수, "edge 중 핵심 부위 안" 수, 해상도)을 아래 표에 적는다. 결과가 나오기 전에는 임계값·`edge` 판정 규칙을 바꾸지 않는다.

| # | 자세 | 기대·판정 | 결과 |
|---|---|---|---|
| 1 | 평소 거리, 정면 | 검출 ≥ 95%, 찾지 못한 시간 ≈ 0, 분석한 시간 ≈ 답변 시간. 일부 프레임 밖 시간이 크면 H1 후보 | 미실행 |
| 2 | 카메라에 가까이(이마 위가 잘리게) | 실시간 문구 "얼굴 위쪽이 화면 밖에 있어요", 진단 "핵심 부위 안: 예" → H1 확인 | 미실행 |
| 3 | 턱이 잘리게 | "아래쪽" | 미실행 |
| 4 | 몸을 기울여 미리보기의 오른쪽 가장자리로, 이어서 왼쪽으로 | 문구 방향이 미리보기와 일치(좌우 반전 확인) | 미실행 |
| 5 | 5초 이상 자리 비움 | 찾지 못한 시간 ≈ 5초, 1초 이상 1번 | 미실행 |
| 6 | 안경·어두운 조명 | 잠깐씩 `none`이 생기는지(H2), 찾지 못한 시간과 횟수 | 미실행 |
| 7 | 답변 중 다른 탭으로 5초 | 분석하지 못한 시간 ≈ 4~5초, 다른 지표에 섞이지 않음 | 미실행 |
| 8 | 진단의 카메라 해상도 | 640×480이 아니면 H3. 미리보기에 검은 띠와 함께 프레임 전체가 보이는지 | 미실행 |

### G 0단계 실현 가능성 시험 (실제 웹캠, 미실행)

[설계](superpowers/specs/2026-11-01-g-gaze-calibration-design.md) 13절. 구현: `feature/gaze-calibration`(0단계만). 자동 테스트는 가짜 검출기(합성 얼굴)로 계산·흐름만 확인했다. **실제 웹캠 정확도는 아래 시험 전까지 모른다.** 판정은 1단계로 갈지 정하는 실험 기준이고, 통과해도 정확도 보장이 아니다.

**실행**
1. 백엔드를 켠다(`cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000`).
2. 웹은 실험실을 켠 개발 서버로 다시 띄운다: `cd web && VITE_GAZE_LAB=true npm run dev`. 이미 떠 있는 개발 서버(`npm run dev`)에는 실험실이 없다.
3. 브라우저(Chrome 권장)에서 `http://localhost:5173/dev/gaze-lab` → "동의하고 카메라 켜기" → "얼굴이 화면 안에 있어요" 확인.
4. 시험 전 메모: 날짜, 노트북 모델, 브라우저·버전, 화면 크기와 실험실에 표시된 뷰포트·배율·카메라 해상도, 카메라 위치(내장 위 가운데 등), 대략적인 거리, 조명, 안경 여부, 함께 돌던 무거운 프로그램.

**시험(약 3분, 3번 반복)**
1. "시험 시작" → 화면 안내를 따른다. 안내가 없으면 고개는 그대로 두고 눈으로만 본다. 시험 중 창 크기·위치·확대/축소를 바꾸지 않는다(바뀌면 그 실행은 무효).
2. 렌즈 단계: 카메라 렌즈 자체를 본다(외장 카메라면 그 렌즈).
3. 거리 단계: 안내에 따라 몸을 약 10cm 앞으로, 이어서 뒤로 기울인 채 본다.
4. 주기 단계(초당 4·10·15회 각 20초, 글 입력 20초): 그동안 OS 작업 관리자에서 브라우저 CPU 사용률을 본다.
5. 결과가 나오면 "집계 복사(JSON)"로 복사해 아래 표와 함께 남긴다(영상·특징점·좌표는 들어 있지 않다).
6. "시험 시작"으로 2번 더(매번 새로 보정). 가능하면 안경을 쓰거나 조명을 낮춰 1번 더.
7. (선택) 시험 중에 창 크기를 바꿔 "이번 시험은 무효예요"가 뜨는지 본다.

**기록표** — 실행 1: 2026-11-03, 뷰포트 958×910(창이 최대화되지 않음), 배율 1, 카메라 640×480. 진단 항목 추가 전 실행이라 진단 수치 없음. 판정은 3번 중 2번 기준이라 아직 결론 아님

| 항목 | 실행 1 | 실행 2 | 실행 3 | 안경·저조도 |
|---|---|---|---|---|
| H1: 처음 보는 응시 AUC · 렌즈 정면 toward · 고개 돌림 toward · 위쪽 띠 오판 · 판정 | 0.37 · 0% · 0% · 0% · 실패(교차 검증 AUC 0.85, 화면 오판 0%) | | | |
| H2: 오차 중앙 px(너비 %) · 80% · 고개 돌림 비율 · 유효 표본 · 모델 · 판정 | 181px(19%) · 239px · 0.65 · 100% · M1 · 실패(교차 검증 310px) | | | |
| 질문 패널 32·120·240px: 적중 / 패널 밖 question 오판 · 최소 사용 가능 높이 | 세 높이 모두 판정 불가(2×e80 ≈ 478px 필요) · 없음 | | | |
| 거리 앞·뒤: 막힌 표본 · 오차 비율 · 판정 | 100%·100% · – · 통과(자세 변화 감지) | | | |
| 주기 4·10·15: 실제 주기 · 검출 p95 · 메인 스레드 점유 · 지연 p95 · 긴 작업 · 얼굴 검출(D) | 4.0·10.0·15.0 · 22·21·21ms · 7·18·27% · 14ms · 0 · 100% · 통과 | | | |
| 글 입력 중 지연 p95 · OS CPU 사용률(4·10·15·글 입력) | 13ms · CPU 미기록 | | | |

판단 순서: H1(렌즈와 화면 위쪽 구별) → H2·질문 패널(필요한 패널 크기) → 주기(기본 후보). 결과를 보고 G1 포함 여부, 질문 패널 크기(화면 변경은 따로 결정), 기본 주기를 정한 뒤 1단계 계획을 고친다.

## 보안 검토 필요

- **React Router 취약점(2026-10-28 `npm audit`):** 설치본 `react-router-dom@6.30.6`·`react-router@6.30.6`(package.json `^6.28.0`)이 두 권고의 영향 범위(6.0.0~7.17.0)에 들어 Moderate 2건으로 보고됨. 수정 버전은 7.18.0 이상이고 `npm audit fix --force`는 7.x 메이저 업그레이드(호환성 깨짐)라서 실행하지 않았음. 이전 리뷰(P2-8)의 "영향 없음" 판단은 틀렸으므로 이 기록으로 대체함.
  - GHSA-337j-9hxr-rhxg(SSR 하이드레이션의 `deserializeErrors()`): 이 앱은 `BrowserRouter` 기반 Declarative Mode(`web/src/main.tsx`)이고 SSR을 쓰지 않으므로 해당하지 않는 것으로 판단.
  - GHSA-wrjc-x8rr-h8h6(`<Link>`·`useNavigate`의 백슬래시 오픈 리다이렉트): SSR과 무관하므로 위 판단으로 배제되지 않음. 코드 검색(grep) 기준으로 `Link`/`nav()`에 넘기는 값은 고정 경로와 서버가 준 id뿐이고 URL 쿼리 등 사용자 입력을 경로로 넘기는 곳은 찾지 못했음. 정식 검토와 7.x 업그레이드 여부는 결정 전.

## 미해결 문제

- 메모리가 부족할 때(여유 수십 MB, 스왑 가득) 전체 e2e의 desktop `camera.spec.ts`가 시간 초과로 실패함(2026-11-03, 브랜치 전 코드에서도 재현, 메모리가 풀리면 9/9 통과). 이 PC에서는 VS Code 창 둘(Pylance 포함)과 다른 AI 세션이 메모리를 많이 씀. e2e는 메모리가 넉넉할 때 돌릴 것. 이번 통합 전체 검증의 desktop/mobile 카메라 테스트는 모두 통과함.
- `web/e2e/gaze-lab.spec.ts`의 "dots are drawn exactly where they are scored"가 가끔 `NaN`으로 실패함(테스트 경쟁 상태, 위 "자동 테스트" 참고). 이번 통합 전체 검증에서는 통과했지만 경쟁 상태 자체는 수정하지 않음. 점을 찾고 재는 것을 한 번의 `page.evaluate`로 묶는 수정 필요(미적용).
- 회고 한눈에 보기의 비치명적 접근성 개선(미적용): 앱 전체 링크 색 `--accent`가 밝은 화면에서 4.30:1(일반 글자 기준 4.5:1 미만, 앱 전체 토큰이라 R1에서 바꾸지 않음), 앱 전체 `--muted` 3.41:1(카드 밖), 막대·격자 칸의 마우스 툴팁(`title`)은 키보드로 볼 수 없음(같은 값은 표 보기·답변 카드에 있음), 표 보기에 제한·평균 값 행이 없음(그래프 제목 옆 글자로는 있음).
- e2e 설정은 PATH의 `python`을 씀. venv를 PATH에 넣지 않으면 백엔드가 뜨지 않음.
- 이 머신의 Playwright 브라우저는 2026-10-30에 v1248로 다시 받았지만 시스템 라이브러리(`libnspr4`·`libnss3`·`libasound2t64`)가 없어 `LD_LIBRARY_PATH=$HOME/.cache/playwright-syslibs/root/usr/lib/x86_64-linux-gnu`로 지정해야 뜸(없으면 모든 e2e가 브라우저 시작에서 실패). 근본 해결은 `sudo npx playwright install-deps chromium`.
- 로컬 STT 실패 사유(무음·바쁨·모델 실패 등)는 답변마다 저장하지 않아 화면은 "인식하지 못했거나 전사 요청이 실패했어요"로만 알림(서버 로그와 `/health`의 `stt.error`에는 남음). 사유별 안내가 필요하면 DB 컬럼 추가(스키마 변경 3곳)가 필요함.
- 로컬 STT는 동기 라우트 안에서 돎. 첫 전사 때 모델을 내려받으면 그 요청이 다운로드 시간만큼 걸림(미리 `python -m app.stt download` 권장).
- 앱 로거(`app.stt`)의 INFO 로그(모델 로딩·전사 시간)는 uvicorn 기본 설정에서 출력되지 않음. WARNING만 보임.
- 확장은 `setAccessToken()`으로 넣은 토큰만 보냄. 토큰을 넣는 로그인 쪽이 없어 `AUTH_DISABLED=false` 환경에서는 여전히 401이 남(웹 토큰 제공자 등록도 팀원 연동으로 남음, D-26).
- 2026-11-03 이전 로컬 SQLite에 같은 사용자의 같은 URL 지원 건이 이미 두 건 이상 있으면 `applications_user_url_uq`를 만들지 못하고 경고만 남김. 그 DB는 겹친 건을 정리한 뒤 다시 시작해야 SQLite에서도 409가 남.
- 새 행 잠금(문항 버전, 답변 업로드)과 URL 고유 인덱스의 동작은 SQLite로만 검사함. 실제 Postgres·Supabase에서 동시 요청 확인 필요.
- `recorded_at`은 이제 업로드를 시작한 시각(전에는 커밋 시각). 필드 이름·형식은 그대로지만 값의 뜻이 조금 바뀜(D-23).
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
5. 팀원 연동: 웹 로그인 토큰 제공자(`setAuthTokenProvider`), ① Apply 확장의 `/track/sync` essays 전송, 확장 `setAccessToken()` 호출.

## 이어서 작업할 때

- 환경: WSL2 Ubuntu, Python 3.12 venv(`backend/.venv`), `web/node_modules`가 설치돼 있음. `backend/.env`가 있음(내용은 열지 말 것).
- 기능 배경은 [docs/plans/2026-10-15-evidence-interview.md](plans/2026-10-15-evidence-interview.md)와 README의 "연습 전용 원칙과 P0 기능" 절에 있음. 경쟁 분석 보고서(`research/reports/Final Round AI 경쟁 분석.md`)는 프로젝트 공유 폴더에 있고 이 저장소에는 없음.
