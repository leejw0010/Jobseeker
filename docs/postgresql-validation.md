# 격리 PostgreSQL·JWT·RLS 검증

`backend/integration/`은 실제 PostgreSQL 16.15 및 PostgREST 16.5를 사용하는 별도 검증입니다. 일반 `backend/.venv/bin/python -m pytest -q`는 `backend/pytest.ini`에 따라 기존 SQLite 테스트만 실행합니다. 이 검증은 Supabase 클라우드·Auth 서버·Storage 서비스 자체의 동작을 검증하지 않습니다.

## 준비와 실행

Linux x86-64, Python 가상환경의 `requirements-dev.txt`, gcc/make, zlib 헤더, tar/dpkg-deb가 필요합니다. 시스템 설치나 sudo는 사용하지 않습니다.

```bash
# 저장소 루트. 공식 배포본을 내려받아 /tmp 아래에서만 빌드·압축 해제합니다.
backend/.venv/bin/python scripts/setup_pg_validation_runtime.py

# 기존 tests/conftest.py의 SQLite 강제 설정과 분리된 실행
cd backend
.venv/bin/python -m pytest -q integration
```

기본 런타임 폴더는 `/tmp/jobseeker-pg-validation-runtime`입니다. 다른 `/tmp` 하위 폴더를 사용하려면 준비 스크립트에 `--runtime /tmp/전용폴더`를 주고 검증에 `JOBSEEKER_PG_RUNTIME=/tmp/전용폴더`를 줍니다. 소스 빌드는 최대 두 작업만 병렬 실행합니다. 초기 실행에는 네트워크·로컬 소켓 사용 권한이 필요합니다. 실패한 준비의 세부 출력은 해당 임시 폴더의 `configure.log`, `build.log`, `install.log`, `setup.log`에 남습니다.

각 검증 실행은 별도의 모드 0700 임시 클러스터를 생성하며 종료 시 중지·삭제합니다. PostgreSQL TCP는 끄고 전용 Unix 소켓만 사용합니다. FastAPI와 PostgREST는 루프백에만 바인딩합니다. 설정은 `shared_buffers=32MB`, `max_connections=32`, `work_mem=2MB`, `maintenance_work_mem=16MB`, PostgREST 풀 2입니다. `fsync`, `synchronous_commit`, `full_page_writes`를 모두 켜서 실제 트랜잭션 내구성을 유지합니다.

매 실행 48바이트 난수로 JWT 서명 비밀값을 생성하고 자격증명 파일을 만들거나 출력하지 않습니다. 오디오도 합성 바이트만 임시 폴더에 씁니다. STT는 끄고 OpenAI·Supabase 서비스 키를 비워 실제 외부 요청을 막습니다. 기본 로그는 임시 클러스터와 함께 삭제되며 `JOBSEEKER_KEEP_PG_LOGS=1`을 명시하면 비밀값을 지운 로그만 `backend/integration/results/`에 남깁니다.

## 검증 범위

- 전체 `supabase/schema.sql`로 만든 새 DB 및 최초 스키마 커밋 `ec5e1bd8270947e3e02c13521c1b4716414bd698`에서 모든 증분 SQL을 적용한 DB를 비교합니다. 마이그레이션 반복 실행, 기존 자소서·전사문·제출 플래그 보존, 정확한 은행 문항에만 적용하는 분류 보정, 기존 답변의 NULL 스냅샷, UUID/jsonb/제약/RLS 카탈로그를 확인합니다.
- FastAPI는 테이블 소유자인 제한된 DB 역할(`validation_owner`, 슈퍼유저 아님)로 실행합니다. 여기서는 RLS 우회 가능성을 전제로 라우터의 A/B 사용자 소유권 필터를 실제 서명 JWT로 검증합니다.
- PostgREST는 테이블 소유자가 아니며 `NOSUPERUSER NOBYPASSRLS NOINHERIT`인 `validation_authenticator`로 접속한 뒤 JWT의 `authenticated` 역할로 전환합니다. 일반 사용자에 테이블 DML 권한을 명시적으로 주고 SQL의 RLS 정책이 사용자별 읽기·쓰기와 교차 부모 연결을 막는지 확인합니다. 실제 `current_user`, `session_user`, `auth.uid()` 및 A/B/A/B 풀 재사용을 확인합니다.
- 잘못된 서명·만료·대상·UUID·익명 역할·허가되지 않은 역할, 교차 사용자 세션·문항·자소서·버전·코칭·확정 제출 이력을 검사합니다. 제출 이력은 소유한 문항의 제출 버전에만 INSERT 가능하며 UPDATE/DELETE로 사라지지 않는지 확인합니다.
- 실제 동시 HTTP 요청으로 같은 URL과 새 자소서 문항을 저장하고, 서로 다른 초안·복원·단계 이력을 추가합니다. 실제 PostgreSQL 행 잠금을 잡고 API 캡처가 기다리는 것을 관찰한 뒤 분류/태그를 함께 바꾸어 스냅샷 원자성과 필터 변경의 409를 확인합니다.
- 기능을 켜고 끈 뒤 다시 켜는 재시작에서 분류 스냅샷과 녹음/전사/코칭 식별자의 보존·무효화를 검사합니다. 미적용 스키마에서 기능을 켜면 앱 시작이 실패하는지도 확인합니다.

이 하네스는 SQL 파싱과 정책 실행에 필요한 `auth.users`, JWT 클레임을 읽는 `auth.uid()`, Storage 버킷/객체/폴더 함수만 최소 구성합니다. Supabase Auth 발급, 관리형 DB 권한 기본값, Storage 업로드·다운로드 정책, 실제 클라우드 마이그레이션 적용은 별도 검증 대상입니다. 역할/권한은 하네스에 명시되어 있으며 클라우드에서 이미 설정되어 있다고 가정하지 않습니다.

## 인증 설정

인증은 기본으로 켜집니다. 로컬 개발·테스트만 `AUTH_DISABLED=true`를 명시할 수 있고 `APP_ENV=production`과 함께 사용하면 시작 오류입니다. 인증을 켜면 `SUPABASE_URL`로 issuer를 고정하고 `aud=authenticated`, `exp`, UUID `sub`를 필수 검증합니다.

기존 HS256은 `SUPABASE_JWT_MODE=hs256`과 백엔드 `SUPABASE_JWT_SECRET`을 사용합니다. 공개 키 프로젝트는 `SUPABASE_JWT_MODE=jwks`로 설정하며 비밀값은 필요하지 않습니다. JWKS 주소는 설정한 프로젝트의 `/auth/v1/.well-known/jwks.json`으로만 만들고 토큰의 `jku`/`x5u`를 신뢰하지 않습니다. 허용 알고리즘은 RS256/ES256이며 HS256과 모드를 섞지 않습니다. PyJWT의 키 집합 캐시는 5분, 요청 타임아웃은 5초이며 현재 잠금 버전은 알 수 없는 `kid` 재조회에 30초 제한을 둡니다.

로컬 HTTP JWKS 서버를 사용하는 `backend/tests/test_auth_jwks.py`에서 RS256·ES256 서명, `kid` 회전(재조회 제한 경과 후), 잘못된 클레임, 서버 오류와 HS256 혼동 공격을 검증합니다. 실제 Supabase 공개 키 조회나 로그인은 수행하지 않습니다.

## 공식 출처와 고정 버전

- [PostgreSQL 16.15 배포 목록](https://www.postgresql.org/ftp/source/v16.15/): 소스 SHA256 `c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed`.
- [PostgREST v16.5 공식 릴리스](https://github.com/PostgREST/postgrest/releases/tag/v16.5): Linux static x86-64 자산 SHA256 `5099e7ada38f9f6846cd87c14c5f158b7c165f1e9959665ad412e61f4dceba95`를 공식 GitHub 자산 metadata와 비교합니다.
- [Ubuntu 공식 OpenSSL 패키지 저장소](https://archive.ubuntu.com/ubuntu/pool/main/o/openssl/): `libssl-dev_3.0.13-0ubuntu3.16_amd64.deb`의 APT metadata SHA512를 고정해 검증한 뒤 임시 폴더에만 압축 해제합니다. 시스템 패키지 설치·업그레이드는 하지 않습니다.

## 2026-11-05 실행 결과

`cd backend && .venv/bin/python -m pytest -q integration --tb=short`: **16 passed in 28.67s**. 실제 격리 PostgreSQL/PostgREST에서의 자동 검증이며 실제 Supabase 클라우드 확인은 아닙니다. 로컬 JWKS/인증/설정만 별도로 실행한 결과는 **47 passed in 5.61s**입니다.


2026-11-06 최종 재검증: **17 passed in36.18s**. 이전16개에 직접 사용자 JWT의 버전 본문/소속 변경·제출 취소·단독 삭제 거부와 명시적 부모 삭제 cascade 검증이 추가됐다. [최종 결과](validation/2026-11-06-usability-results.md). 이17개에도 관리형 Supabase Auth/Storage 서비스 검증은 포함하지 않는다.
