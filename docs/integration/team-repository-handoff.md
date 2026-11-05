# 팀 저장소 Practice·Track 이식 안내

작성 기준: 2026-11-06 원격 읽기 전용 재확인. **팀 `frontend/`를 최종 서비스의 기준으로 유지한다.** 이 문서는 이식 준비이며 팀 저장소 변경·빌드·배포를 수행했다는 뜻이 아니다.

## 1. 확인한 두 저장소

- 원본: `leejw0010/Jobseeker`, main `e7e79679fcccc5ee862377ae81be407254d6e46e` + 이 PR의 안정화 수정.
- 팀: `seungxa/26-2_CapstoneProject`, `feature/frontend`의 [ec7b279](https://github.com/seungxa/26-2_CapstoneProject/commit/ec7b279eda87b5dd49beadff453947aa32309e62). 커밋 시각은 2026-11-05 20:37:54 KST이며 제목은 `feat: update profile form and add JSON export`다. 이식 직전 다시 확인할 것.

이전 확인 SHA `cc7b5b2ae08d4c830d9fdca987e7a90501c16e06`에서 [1커밋 전진](https://github.com/seungxa/26-2_CapstoneProject/compare/cc7b5b2ae08d4c830d9fdca987e7a90501c16e06...ec7b279eda87b5dd49beadff453947aa32309e62)했다. 변경은 `App.css` 218줄 추가, 신규 `lib/archiveFields.ts` 306줄, `Profile.tsx` 450줄 추가/304줄 삭제다. App·Login·Signup·ProtectedRoute·Dashboard·Apply와 package/lock은 이 커밋에서 바뀌지 않았다. 특히 Profile의 DB 계약이 기존 `basic/education/sections`에서 `archive`로 바뀌었으므로 6절의 확인 절차가 필요하다.

| 항목 | 원본 manifest → lock | 팀 manifest → lock |
|---|---|---|
| React/DOM | ^18.3.1 → 18.3.1 | ^19.2.8 → 19.3.1 |
| Router | react-router-dom ^6.28.0 → 6.30.6 | react-router ^8.4.0 → 8.4.0 |
| Vite | ^6.0.0 → 6.4.4 | ^8.3.0 → 8.3.4 |
| TypeScript | ~5.6.3 → 5.6.3 | ~6.0.2 → 6.0.3 |
| Supabase JS | 없음 | ^2.118.0 → 2.118.0 |
| MediaPipe tasks-vision | ^1.1.1 → 1.1.1 | 없음 |

근거: 최신 SHA의 팀 [package.json](https://github.com/seungxa/26-2_CapstoneProject/blob/ec7b279eda87b5dd49beadff453947aa32309e62/frontend/package.json), [lock](https://github.com/seungxa/26-2_CapstoneProject/blob/ec7b279eda87b5dd49beadff453947aa32309e62/frontend/package-lock.json). 위 lock 버전은 이전 확인과 같다. 팀 Router lock의 Node 요구는 **22.22.0 이상**이다(Vite는 `^20.19.0 || >=22.12.0`, Supabase JS는 `>=22.0.0`). 확인한 최신 전체 tree에는 tsconfig와 ESLint 설정, 백엔드·SQL migration·확장 코드가 없지만 build 명령은 `tsc -b && vite build`이므로 팀의 기준선 빌드와 실제 별도 코드 위치는 확인해야 한다. 이 문서 작성 중 팀 설치·빌드·실행은 하지 않았다.

## 2. 팀에서 유지할 요소

`frontend/src/main.tsx`, `App.tsx`의 단일 BrowserRouter·로그인 상태·공통 header, Dashboard·Login·Signup·Profile·Apply 및 ProtectedRoute를 유지한다. Practice/Track placeholder에 기능 페이지를 연결한다. 원본의 main/App·전체 사이드바를 복사해 팀 앱을 대체하지 않는다.

현재 팀 Apply는 여전히 110바이트 placeholder다. 채용 사이트 자동입력·제출 감지·확장 구현을 이 브랜치에서 확인한 것으로 보고하지 않는다. 최신 Profile·`lib/archiveFields.ts`·프로필 JSON 내보내기와 관련 CSS는 팀 소유로 유지한다. 팀 Profile과 입력 자료를 자동으로 LLM에 전송하지 않는다.

## 3. 파일 단위 이식안

목적지 기준은 `frontend/src/features/practice-track/`다. 원본의 상대 import를 유지하면서 팀 소유 파일과 분리한다.

| 원본 | 목적지 / 처리 |
|---|---|
| web/src/api.ts, types.ts, sttText.ts | 기능 폴더 아래 동명 파일. SDK·Router 독립 API 계약 유지 |
| web/src/pages/PracticeHome.tsx | 기능 pages/PracticeHome.tsx |
| web/src/pages/SessionRunner.tsx, SessionReview.tsx | 기능 pages/ 동명 파일 |
| web/src/pages/SessionList.tsx, PracticeSettings.tsx | 기능 pages/ 동명 파일 |
| web/src/pages/TrackList.tsx, ApplicationPage.tsx, StatsPage.tsx | 기능 pages/ 동명 파일 |
| web/src/components/*, components/track/* | 기능 components/ 동명 경로. 동의·녹음·diff 포함 |
| web/src/practice/*, review/*, delivery/*, video/* | 기능 폴더의 동명 경로. 순수 계산과 탭 내 관측 보존 |
| web/src/pages/GazeLab.tsx와 CSS | 개발 전용 경로와 flag만. 일반 면접 평가에 노출하지 않음 |
| web/src/styles.css | 기능 전용 스타일로 범위를 제한한 뒤 이식 |
| web/src/App.tsx, main.tsx | **복사하지 않음** |
| 팀 frontend/src/lib/archiveFields.ts·pages/Profile.tsx | **팀 원본 유지**. Practice/Track 타입으로 대체하거나 프로필 자료를 자동으로 읽어 코칭하지 않음 |
| backend/ | 별도 FastAPI 서비스. 팀 frontend는 VITE_API_URL로 연결 |
| supabase/schema.sql, migrations/* | 현재 팀 catalog와 대조할 기준. 무검토 전체 실행 금지 |
| extension-track/ | Apply 확장의 실제 코드·인증 수명 확인 후 별도 이식 |

팀 `pages/Practice.tsx`, `Track.tsx`는 기능 route wrapper로 연결하고 기존 ProtectedRoute 안에 둔다. 원본 App의 health/STT 안내·기록/설정/통계 링크는 기능 wrapper로 가져온다. 모든 업무 로직을 root Router에 넣지 않는다.

## 4. 라우트 대응

| 원본 | 최종 팀 라우트 |
|---|---|
| /practice | /practice |
| /practice/history | /practice/history |
| /practice/settings | /practice/settings |
| /practice/sessions/:id/run | /practice/sessions/:id/run |
| /practice/sessions/:id | /practice/sessions/:id |
| /track | /track |
| /track/stats | /track/stats |
| /track/:id | /track/:id |
| /dev/gaze-lab | 개발 빌드만, 제품 라우트에서 제외 |

팀 root에 `/practice/*`, `/track/*`를 추가하되 두 번째 Router를 만들지 않는다. 현 팀의 `featurePages.includes(location.pathname)`은 하위 경로에서 메뉴를 숨기므로 prefix 경계 판정으로 바꿀 필요가 있다. SPA deep-link rewrite와 `/track/stats`/`:id` 구분도 검증한다. `?application=<UUID>`와 session/answer의 id param은 보존한다.

## 5. 인증·API 클라이언트

팀의 `src/lib/supabase.ts` singleton을 그대로 쓴다. 현재 source는 환경변수 이름만 제공하며 실제 프로젝트·서명 알고리즘은 **미확인**이다. publishable key는 사용자 액세스 토큰이 아니다.

API 모듈은 `configureApiClient({baseUrl,getAccessToken,onUnauthorized,onSessionReset})`, 기존 `setAuthTokenProvider`, 개별 `createApiClient`를 제공한다. 팀 host에서 한 번 등록한다:

```ts
configureApiClient({
  baseUrl: import.meta.env.VITE_API_URL,
  getAccessToken: async () => (await supabase.auth.getSession()).data.session?.access_token ?? null,
  onUnauthorized: async () => {
    const { error } = await supabase.auth.refreshSession();
    if (error) throw error;
  },
  onSessionReset: () => { /* 기능 root unmount: 녹음/카메라/편집 화면 정리 */ },
});
```

- Supabase SDK가 세션/refresh의 단일 소유자다. 별도 토큰 localStorage·URL·query·DOM 주입을 만들지 않는다.
- 401 refresh는 합쳐서 한 번 수행하고 GET만 한 번 재시도한다. POST·업로드·버전 저장은 자동 재전송하지 않고 입력을 보존해 사용자가 재시도한다.
- `SIGNED_OUT` 또는 사용자 UUID 변경 시 `api.resetSession()`을 호출하고 기능 root의 user key를 교체한다. 진행 요청과 탭 음성/영상 요약을 버리고 스트림은 unmount cleanup으로 종료한다. 토큰 refresh만으로는 사용자 key를 바꾸지 않는다.
- 로그아웃은 서버 녹음 삭제·동의 철회와 다르다. 명시적 개인정보 동작만 서버 삭제를 수행한다.
- 운영은 `APP_ENV=production`, `AUTH_DISABLED=false`. 인증 우회는 시작 오류다. 로컬 테스트만 `AUTH_DISABLED=true`를 명시한다.
- `SUPABASE_JWT_MODE=hs256`은 서버의 기존 secret을, `jwks`는 설정된 SUPABASE_URL의 `/auth/v1/.well-known/jwks.json` 공개키를 사용한다. issuer는 해당 프로젝트 `/auth/v1`, audience는 authenticated, exp와 UUID sub를 검증한다. token의 jku/issuer가 키 조회 대상을 결정하지 않는다.
- 비대칭 키는 RS256/ES256 검증과 kid 교체를 로컬 대역으로 검사한다. 실제 팀 토큰/issuer/키 회전·폐기는 팀 테스트 환경에서 추가 검증해야 한다. HS256 secret은 프론트엔드·확장에 두지 않는다.

## 6. Supabase와 profiles

최신 팀 [Profile source](https://github.com/seungxa/26-2_CapstoneProject/blob/ec7b279eda87b5dd49beadff453947aa32309e62/frontend/src/pages/Profile.tsx)는 `profiles.user_id`로 **`archive`만 조회**하고 `{user_id, archive, updated_at}`을 `onConflict: 'user_id'`로 upsert한다. 이전 SHA의 `basic/education/sections` 조회·저장은 현재 코드 계약이 아니다. JobSeeker에는 profiles 테이블이 없으며 이 PR은 이를 만들거나 수정하지 않는다.

새 [archiveFields.ts](https://github.com/seungxa/26-2_CapstoneProject/blob/ec7b279eda87b5dd49beadff453947aa32309e62/frontend/src/lib/archiveFields.ts)의 `Archive`는 `schemaVersion: '1'`, `profile` 문자열 사전과 `education/experience/military/language/license/activity/award` 문자열 사전 배열이다. 그룹별 최대100건·개별 값 최대20,000자·JSON 2MB 상한 등의 검증과 명시적 `jobseeker-archive.json` 다운로드가 Profile에 있다. 화면 내 Entry.id는 임시 숫자이며 저장 archive의 영속 ID가 아니다.

이는 **확인한 클라이언트 소스 계약**이다. 최신 tree에 해당 SQL이나 migration이 없으므로 실제 클라우드에 `profiles.archive`가 생성됐는지, 이전 `basic/education/sections` 데이터가 변환됐는지, RLS가 이를 보호하는지는 미확인이다. `normalizeArchive`는 새 archive 입력을 정규화할 뿐 기존 세 컬럼을 읽어 변환하지 않는다. 팀 데이터 소유자가 기존 행 보존·마이그레이션/호환 정책을 결정하기 전 JobSeeker 이식에서 자동 변환·덮어쓰기를 하지 않는다.

프로필 JSON에는 이름·연락처·주소 등 식별 정보가 포함될 수 있다. 이 파일은 본 PR의 익명 집계 `jobseeker-validation-v1`과 다른 계약이며 미디어 비교 도구에 넣지 않는다. 실제 Apply가 프로필 JSON을 소비하는지 이 tree로는 확인할 수 없고, 동의 없이 Track sync나 코칭 입력에 전체 archive를 추가하지 않는다.

원본 사용자 소유권은 검증한 JWT sub UUID다. 두 기능이 같은 Supabase Auth를 쓰도록 하고, 프로필 내부 Entry.id 숫자를 Application·EssayItem·AnswerVersion UUID로 사용하지 않는다. 실제 profiles.archive 타입·이전 컬럼 보존/변환·unique/FK·RLS, 기존 테이블/정책/인덱스와 비공개 Storage bucket을 catalog로 대조해야 한다. `IF NOT EXISTS`만으로 서로 다른 기존 테이블이 호환되지는 않는다.

기존 migration은 수정하지 않는다. 이 PR의 추가 Track·Practice integrity migration까지 검토한 뒤 **팀용 새 증분 migration**을 별도 PR로 준비한다. 데이터 삭제 down migration 대신 이전 앱/flag로 복귀하고 추가 자료를 남긴다. 실제 클라우드 Auth·RLS·Storage 검증은 로컬 PG/PostgREST 결과와 별도다.

## 7. Apply → Track → Practice 계약

Apply는 추출/입력 보조, Track은 영속 지원·버전·제출·전형 기록이다. 사용자 동의 후 기존 `POST /track/sync`에 회사·직무·분류·URL·문항/답변·지원일·명시 `submitted`를 전달한다. user_id는 본문이 아닌 JWT sub에서 정한다.

- 신규 Apply: 초안 false / 실제 제출 확인 true를 항상 명시한다. 불확실하면 사용자 선택을 받는다. 현재 레포가 별도 Apply 클라이언트의 준수를 강제할 수는 없다.
- 기존 omitted submitted의 true 기본값과 기존 is_submitted는 호환용으로 유지하지만 명시 확인 기록으로 만들지 않는다.
- 동일 사용자·같은 URL은 Application을 재사용한다. 다른 사용자의 동일 URL은 별도다. URL 임의 병합·query 제거를 하지 않는다.
- 문항은 기존 trim한 질문 텍스트 매칭을 유지한다. 원본 사이트가 문항을 바꾸면 자동으로 같은 문항이라고 추정하지 않는다.
- 내용이 달라질 때만 새 버전, 복원은 항상 새 초안, 실제 제출은 버전 ID에 연결한 append-only 확인이다. 반복 sync/같은 버전 연속 확인은 중복 자료를 만들지 않는다.
- sync 응답 application_id로 `/track/<id>`와 `/practice?application=<id>`를 연결한다. 세션 시작은 서버가 소유권을 다시 확인하고 선택한 버전 본문·ID를 context로 복사한다. 이후 Track 수정·복원·삭제가 과거 세션을 재작성하지 않는다.
- 확장 session 저장소의 setAccessToken 교체/삭제·401/재로그인 접점을 연결해야 한다. 팀의 실제 로그인 전달 채널은 아직 연결하지 않았으며, 허용 origin·extension ID·사용자 gesture를 검토한 별도 통합이 필요하다.
- 팀의 새 Profile JSON 내보내기는 확인했지만 Apply 페이지에는 수신·자동입력·Track 저장 구현이 없다. 프로필 archive 전체와 Track의 공고/문항/답변/제출 계약을 같은 데이터로 취급하지 않는다.

## 8. 의존성·스타일 호환

현재 원본 React/Router/Vite를 업그레이드하지 않는다. 팀 이식 시 페이지 adapter의 react-router-dom import를 팀 react-router로 바꾸고 React 19/TS6 컴파일 오류를 개별 수정한다. 새 업무 모듈은 Router·SDK를 import하지 않는다.

팀에 없는 MediaPipe와 WASM/모델 자산만 필요한 범위로 추가한다. worker·모델 경로·CSP·GPU→CPU fallback을 검증한다. `:root`, body, a, button, label, .main 등의 원본 전역 CSS를 그대로 가져오지 말고 기능 wrapper 아래로 제한한다. 최신 커밋의 Profile/archive용 `App.css` 추가분도 유지하고 팀 Auth/Profile/header의 시각 회귀를 검사한다.

## 9. 테스트 이전

순수 계산/확장 unit과 backend pytest는 그대로 보존한다. 페이지 E2E의 사용자 시나리오는 유지하고 host route·권한·로그인 fixture만 adapter로 바꾼다. 팀 로그인은 실제 로그인 대역과 별도 실계정 검증을 둔다. 테스트 데이터/녹음은 매 실행 임시 폴더이며 사람 파일럿과 분리한다.

원본 자동 검증 결과는 이 PR의 progress/검증표를 따른다. 팀 앱의 실제 build·React19·모바일 Safari·카메라 권한·실제 Chrome·외부 채용 사이트·클라우드 정책이 검증된 것으로 전용하지 않는다.

팀 회귀에는 새 Profile의 archive 조회/저장·미저장 변경의 JSON 확인·기존 행 호환·학교 구분/어학 등 입력 검증을 포함한다. 이 문서의 최신 원격 소스 검토는 그 기능들의 실행 테스트를 대신하지 않는다.

## 10. 실제 통합 순서와 차단 조건

1. 팀 최신 commit과 기준선 build, 설정 파일 관리 위치를 확인하고 복구 가능한 통합 브랜치를 만든다.
2. 실제 Supabase public signing metadata·profiles.archive 및 기존 프로필 데이터 보존/변환·catalog·Storage·Apply 위치를 확인한다. 운영 데이터 변경은 별도 승인 대상이다.
3. 테스트 프로젝트에 필요한 증분 migration을 적용하고 A/B 실제 JWT로 API와 직접 REST RLS를 각각 확인한다.
4. API client·types·순수 모듈을 먼저 이식하고 기존 Supabase 세션 adapter를 연결한다.
5. Track 페이지/통계와 Apply sync를 연결한 뒤 Practice 선택·스냅샷·녹음·코칭을 연결한다.
6. route/CSS/WASM/CORS·deep links를 정리하고 원본 unit/backend/E2E와 팀 auth/profile 회귀를 실행한다.
7. 비용 0 자동 증거와 실제 모델·사람 측정·외부 서비스 증거를 구분해 PR로 검토한다. Gaze 평가는 계속 비활성화한다.

현재 미확인: 팀 실제 서명 방식과 키 배포, profiles.archive DDL/RLS와 기존 프로필 변환, 테이블 충돌, Apply 확장 구현/JSON 수신, 팀 기준선 빌드, 배포 origin/CORS/CSP, 실제 기기·외부 사이트 동작. 이 항목을 확인하기 전 팀 통합·배포 완료로 표시하지 않는다.
