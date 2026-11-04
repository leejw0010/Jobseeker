# AGENTS.md

JobSeeker(캡스톤 26-2) 중 **② Practice(AI 면접 연습)** 와 **③ Track(지원 이력·자소서 버전 관리)** 을 구현한 저장소입니다. 기능 설명·실행 방법·API 목록은 [README.md](README.md)에 있으니 여기서 반복하지 않습니다.

스택: FastAPI + SQLAlchemy 2(백엔드), React 18 + TypeScript + Vite(웹), Supabase Postgres/Auth/Storage(배포), OpenAI Chat·STT(선택), Chrome MV3 확장.

## 디렉터리 책임

| 경로 | 책임 | 건드릴 때 주의 |
|---|---|---|
| `backend/` | FastAPI API(`app/routers/practice.py`, `track.py`), 모델, 코칭·디브리프·녹음 보관 로직, pytest | 실제 사용자 격리는 라우터의 `user_id` 필터가 담당 |
| `web/` | React 화면, API 클라이언트(`src/api.ts`), 타입(`src/types.ts`), Playwright e2e | 백엔드 응답 형식과 `types.ts`를 함께 맞출 것 |
| `supabase/` | 새 프로젝트용 `schema.sql`, 기존 프로젝트용 `migrations/*.sql`(SQL Editor에서 수동 실행) | 아래 "보호 대상" 참고 |
| `extension-track/` | 공고 저장 팝업. `POST /track/sync`, `GET /track/applications`, `GET /track/stats`만 사용 | 빌드 단계 없음. 배포 주소는 `manifest.json`의 `host_permissions`에도 추가 |
| `docs/` | 아래 "참고 문서" | `docs/screenshots/coaching-review-*.png`는 e2e가 덮어씀 |

## 보호 대상 (변경 전 사용자 확인)

- **API 계약:** 기존 경로·메서드·요청/응답 필드의 이름과 의미를 바꾸거나 지우지 않습니다. 추가는 가능하나 `web/src/types.ts`와 README의 API 표를 함께 갱신합니다. `POST /track/sync` 형식은 팀원 ① Apply 확장이 쓰므로 특히 유지합니다. 화면에서 쓰지 않는 `POST /practice/answers/{id}/feedback`도 호환용으로 남겨 둡니다.
- **DB 스키마:** 이미 있는 `supabase/migrations/*.sql`은 수정하지 않습니다(이미 실행한 프로젝트가 있음). 스키마를 바꾸면 ① `backend/app/models.py` ② `supabase/schema.sql`(새 프로젝트용 전체본) ③ 새 증분 마이그레이션 `supabase/migrations/YYYYMMDD_<이름>.sql`(여러 번 실행해도 안전하게, `if not exists`/`drop policy if exists`) 세 곳을 함께 바꿉니다. `backend/tests/test_migration.py`는 **로컬 SQLite 자동 업그레이드**와 **모든 id 컬럼이 Postgres 방언에서 `UUID`로 컴파일되는지**만 검사합니다. Supabase에서 SQL을 실제로 실행하는 것, RLS 정책·Storage 정책이 동작하는지는 검사하지 않으므로 별도로 확인하고 결과를 `docs/progress.md`에 적습니다. 로컬 SQLite는 `app/db.py`가 빠진 테이블·컬럼만 자동 추가합니다. 타입 변경·컬럼 삭제는 자동으로 되지 않습니다.
- id 컬럼은 `models.ID`(SQLite 문자열 / Postgres uuid)를 씁니다. 사용자 입력 id는 `valid_id()`로 거른 뒤 DB에 보냅니다.

## 개인정보·비밀값

- `backend/.env`, `web/.env*`, `backend/jobseeker.db`, `backend/recordings/`는 읽거나 출력하거나 커밋하지 않습니다. 설정 항목은 `backend/.env.example`을 봅니다.
- `OPENAI_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`은 백엔드에만 둡니다. 웹·확장 코드나 로그, 테스트 고정값, 문서에 넣지 않습니다.
- 녹음은 민감 정보입니다. 동의 없는 업로드·재전사는 403, 전사 후 원본 삭제, `AUDIO_RETENTION_DAYS` 뒤 자동 삭제가 기본입니다. 이 기본값을 약하게 만드는 변경은 하지 않습니다. OpenAI로 보내는 데이터 범위를 넓히면 README의 "OpenAI로 보내는 것"과 동의·설정 화면 문구도 함께 고칩니다.
- 실제 면접 중 답을 띄우는 기능은 만들지 않습니다(연습 전용 원칙).

## 작업 방식

1. 수정 전에 요청 범위와 영향받는 파일(API·스키마·화면)을 확인합니다. 범위 밖 리팩터링, 의존성 추가·업그레이드는 먼저 묻습니다.
2. 동작을 바꾸면 테스트를 추가하거나 고칩니다(백엔드 `backend/tests/`, 화면 흐름 `web/e2e/`).
3. 완료 전에 아래 검증 중 해당하는 것을 실행하고 결과(통과 수·실패 출력)를 그대로 보고합니다. 실행하지 못한 검증은 못 했다고 적습니다.
4. 진행 상태가 바뀌면 `docs/progress.md`, 설계 결정을 내리면 `docs/decisions.md`에 짧게 남깁니다.

## 검증 명령

```bash
# 백엔드 (backend/.venv가 있으면 사용)
cd backend && .venv/bin/python -m pytest -q

# 웹 타입 검사 + 프로덕션 빌드
cd web && npm run build

# 브라우저 e2e: 임시 SQLite·포트 8011/5179로 서버를 직접 띄움. PATH의 python에 백엔드 의존성이 있어야 함
cd web && PATH=../backend/.venv/bin:$PATH npm run test:e2e
#  - Playwright 브라우저 버전이 안 맞으면 CHROMIUM_EXECUTABLE_PATH=<chrome 경로> 지정
#  - 실행하면 추적 중인 docs/screenshots/coaching-review-{desktop,mobile}.png를 덮어씀. 아래 "e2e 스크린샷 보호" 절차를 따를 것
```

pytest와 e2e는 OpenAI·Supabase를 호출하지 않습니다(`conftest.py`와 `playwright.config.ts`가 키를 비움). 실제 외부 서비스 검증은 별도이며 결과를 `docs/progress.md`에 기록합니다. 보고할 때는 "구현돼 있음(코드 확인)", "자동 테스트 통과", "실제 외부 서비스에서 확인"을 구분해서 적습니다.

### e2e 스크린샷 보호

e2e(`web/e2e/coaching.spec.ts`)는 `docs/screenshots/coaching-review-*.png`에 직접 씁니다. 실행 전부터 그 파일에 사용자의 수정이 있을 수 있으므로 `git checkout`/`git restore`를 무조건 실행하지 않습니다. 그러면 실행 전부터 있던 변경까지 지워집니다. 대신 실행 전 상태를 백업하고, 이번 실행이 만든 변경만 백업으로 되돌립니다.

```bash
cd web
git status --short -- ../docs/screenshots/          # 실행 전 상태 확인(수정 표시가 있으면 사용자 변경이므로 보존)
shots=$(mktemp -d) && cp ../docs/screenshots/coaching-review-*.png "$shots"/
PATH=../backend/.venv/bin:$PATH npm run test:e2e
# 스크린샷 갱신이 목적이 아니면 실행 전 상태(사용자 변경 포함)로 되돌림
cp "$shots"/coaching-review-*.png ../docs/screenshots/ && git status --short -- ../docs/screenshots/
```

스크린샷 갱신이 목적이면 되돌리지 않고, 바뀐 이미지를 사용자에게 알린 뒤 커밋 여부를 묻습니다. 스크린샷 경로를 설정으로 빼는 테스트 수정은 아직 하지 않았습니다(`docs/progress.md` 미해결 문제).

## Git · Worktree

- `main`에 직접 커밋하지 않습니다. 작업 브랜치를 만들고 PR로 합칩니다. 브랜치 이름은 관례상 Claude는 `feature/<주제>`, Codex는 `codex/<주제>`를 쓰지만 필수 규칙은 아닙니다. 사용자가 정한 브랜치가 있으면 그것을 씁니다.
- 같은 작업을 이어서 개발할 때는 기존 브랜치와 작업 디렉터리(세션)를 그대로 써도 됩니다.
- 서로 다른 AI(Claude·Codex 등)가 **동시에 파일을 고칠 때**는 같은 작업 디렉터리를 공유하지 말고 브랜치별 `git worktree`(예: `../Jobseeker-<브랜치>`)를 권장합니다. 어떤 경우든 같은 파일을 두 에이전트가 동시에 고치지 않습니다.
- **읽기 전용 리뷰**는 별도 worktree가 필요 없습니다. 현재 작업 디렉터리의 미커밋·미추적 파일도 그대로 읽고 검토할 수 있습니다(단, 위 "개인정보·비밀값"의 파일은 읽지 않음). 리뷰 중에는 파일을 고치지 않습니다.
- 새 worktree에는 `backend/.venv`, `web/node_modules`, `backend/.env`가 따로 필요합니다. `.env`는 사용자가 직접 준비합니다.
- commit·push·merge·rebase·브랜치 삭제는 사용자가 요청할 때만 합니다.
- 커밋할 때는 `git add -A`/`git add .` 대신 파일을 지정해 추가합니다(`.vscode/` 같은 개인 파일이 섞이지 않게).

## 참고 문서 (관련 작업일 때만 읽기)

| 문서 | 읽을 때 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 여러 계층에 걸친 변경, 데이터 흐름·저장 위치 파악 |
| [docs/progress.md](docs/progress.md) | 이어서 작업할 때, 무엇이 검증·미검증인지 확인할 때 |
| [docs/decisions.md](docs/decisions.md) | 기존 동작을 바꾸려 할 때(이유가 기록돼 있는지 확인) |
| [docs/plans/2026-10-15-evidence-interview.md](docs/plans/2026-10-15-evidence-interview.md) | 제출본 기반 코칭·꼬리질문·재연습 수정 |
| [docs/research/interview-products-2026-10-15.md](docs/research/interview-products-2026-10-15.md) | 경쟁 서비스 비교·기능 근거 |
| [extension-track/README.md](extension-track/README.md) | 확장 수정, ① Apply 확장과 통합 |
