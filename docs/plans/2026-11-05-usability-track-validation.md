# Practice·Track 실사용 안정화와 팀 이식 준비

승인 기준: 사용자 「JobSeeker 실사용 안정화 계획 — Track 및 팀 이식 준비 추가」.
기준 main: e7e79679fcccc5ee862377ae81be407254d6e46e.

## Global Constraints

- 운영 Supabase, 사용자 녹음·DB·비밀 설정, 원래 Worktree의 미커밋 실행기 작업에 접근하거나 변경하지 않는다.
- E2E/DB 검증은 임시 DB·녹음 경로만 사용한다. 외부 유료 API 호출 0회.
- 기존 API는 보존하며 추가 필드는 타입과 README에 반영한다. 기존 migration 불변.
- 측정은 탭 메모리와 명시적 익명 JSON 내보내기만. Gaze는 실험실에 유지.
- 팀 frontend/로그인/Profile/Router를 유지. 팀 저장소는 읽기만. 의존성 대규모 업그레이드 금지.
- 이번 브랜치 Commit/Push/PR까지만, 개인 main 병합 금지.

## Task 1: Track core (root)

실패 테스트부터: 수동/legacy override 보존, 날짜/생성/ID 순 이벤트 projection과 편집/삭제, 통계 상호배타 집계, 실제 지원일 월별/미상 추가, 복원 always append, 특정 버전 명시적 제출과 append-only confirmation, Application→EssayItem 잠금, URL·문항·버전 실제 동시성. 공유 models/schemas/SQL/api/types는 root 소유.

## Task 2: Practice stabilization

이전 대화까지 포함한 core input fingerprint, 모델 호출 밖/저장 안 세션 잠금, stale/legacy 처리, dirty transcript vs notes, 단일 지원 기준, 근거 기반 5층 코칭·중복 제거·유형별 outline, 질문/별점 접근성. 순수 UI/계산과 practice services/router 담당, 공유 파일은 root에 요청.

## Task 3: Track UI and extension

지원 CRUD/오류/동시응답·3문항/diff/복원/제출/전형편집·수동유지/통계/mobile/키보드 E2E. Extension은 명시 submitted와 기존 공고 제출전환, typed status/401/logout/relogin, 사용자 gesture 수집만. 실제 팀 로그인 전달은 인터페이스와 대역 검증으로 한정.

## Task 4: Auth and PostgreSQL

격리 PG16/PostgREST rootless, 별도 suite(기존 conftest는 SQLite 강제), 실제 서명 JWT A/B API+nonprivileged RLS 별도 검증, fresh/upgrade/repeat/backfill/legacy/온오프/concurrency/catalog. 인증 default-on/production bypass 거부, configured HS256 or JWKS/issuer/audience/exp/sub/kid rotation, 로컬 JWKS 검증. shared schema 변경은 root와 조정.

## Task 5: Media/Gaze and handoff

PCM/공개 음성/local model, 동일 Face 모델의 사용권 확인 fixture, evidence 분리, versioned aggregate export/stdlib offline compare/실패 분모/invalid 보존, Gaze3회 freshcalib 준비·원인 가설·기존기준 유지. performance/memory·모델 순차 실행. team-repository-handoff.md에 최신 SHA/lock 비교·파일 이식표·route·기존 profiles·Apply→Track→Practice·인증·CSS·Node·테스트·롤아웃 위험 10항목. 실제 human/camera/cloud/AI 품질은 미검증 구분.

## Task 6: Integration and delivery

전체 pytest/build/unit/desktop+mobile E2E/PG/Track-Practice scenarios, 독립 spec+quality 리뷰, 문서 검증표와 정확한 결과, 명시 파일만 commit, push, PR 하나. main/team 변경 없음.
