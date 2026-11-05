# JobSeeker 크롬 확장: 지원 관리 팝업

확장 아이콘을 누르면 뜨는 팝업입니다. ③ Track(지원 관리)과 ② Practice(면접 연습)로 이어 주는 역할을 합니다.

- **이 공고 저장:** 사용자가 **페이지 제목으로 채우기**를 누르면 보고 있는 채용 공고의 회사·직무·직무 분류를 제목 메타데이터로 추정해 채워 줍니다. 팝업을 열기만 해서는 페이지에 스크립트를 주입하지 않으며, 본문·자소서는 수집하지 않습니다. 확인 후 저장하면 지원 관리에 들어갑니다. "지원 완료"를 체크하면 지원일이 오늘로 기록됩니다.
- **이미 저장한 공고:** 같은 URL이면 현재 단계·상태를 보여 주고, 상세 보기나 그 공고로 면접 질문 만들기로 바로 갈 수 있습니다. **지원 완료로 표시**를 직접 누르면 같은 URL의 지원 건에 `submitted: true`를 보냅니다.
- **최근 지원 현황:** 최근 5건과 전체·진행중·합격 수
- **대시보드 열기 / 면접 연습:** 웹 대시보드를 새 탭으로 엽니다.

## 설치(개발용)

1. 백엔드(`backend/`)와 웹(`web/`)을 먼저 실행합니다. 방법은 저장소 루트 README에 있습니다.
2. 크롬 주소창에 `chrome://extensions` 입력
3. 오른쪽 위 **개발자 모드** 켜기
4. **압축해제된 확장 프로그램 로드** → 이 `extension-track` 폴더 선택
5. 퍼즐 아이콘에서 JobSeeker를 고정해 두면 편합니다.

백엔드·웹 주소가 다르면 팝업 오른쪽 위 **설정**에서 바꿉니다. 배포 주소로 바꿀 때는 `manifest.json`의 `host_permissions`에도 추가해야 합니다. 설정 화면은 저장한 API 주소가 `host_permissions`에 없으면 경고를 띄웁니다(백엔드 CORS가 `chrome-extension://`을 허용하므로 요청 자체는 되지만, 배포 주소는 두 곳을 함께 맞춥니다).

## ① Apply 확장과 합치는 방법

팝업만 독립적으로 동작하도록 만들어 두었습니다. ① 확장에 합칠 때는:

- `popup.html`, `popup.css`, `popup.js`, `api.js`, `extract.js`, `settings.js`를 ① 확장 폴더로 옮기고 `action.default_popup`을 `popup.html`로 지정
- `permissions`에 `activeTab`, `scripting`, `storage`, `host_permissions`에 백엔드 주소 추가
- ①이 지원서 제출을 감지하면 같은 `POST /track/sync`에 `essays`(문항·답변)와 `submitted: true`를 보내면 됩니다. 팝업에서 먼저 저장한 공고와 URL이 같으면 같은 지원 건으로 합쳐집니다.
- 로그인을 붙이는 쪽은 `settings.js`의 `setAccessToken(token)`으로 Supabase 액세스 토큰을 넣고, 로그아웃 때 `setAccessToken(null)`을 부릅니다. `api.js`의 `getToken()`이 이 값(`chrome.storage.session`, 브라우저를 닫으면 지워짐)을 읽어 `Authorization: Bearer`로 붙입니다. 토큰이 없으면 개발 모드(`AUTH_DISABLED=true`) 서버에서만 동작합니다.
- 토큰 수명주기 연결: 로그인 성공·토큰 갱신·계정 변경 때 `setAccessToken(nextToken)`, 로그아웃 때 `setAccessToken(null)`을 호출합니다. 팝업은 `chrome.storage.onChanged`를 받아 이전 계정의 목록·공고·진행 중 응답을 무효화합니다. 401은 HTTP 상태를 가진 `ApiError`로 유지하며, 해당 요청에 쓴 토큰만 삭제합니다(그사이 새로 갱신된 토큰은 보존).
- **다시 로그인** 버튼은 설정의 선택 항목 `팀 로그인 주소(loginUrl)`를 엽니다. 빈 값이면 설정 안내를 보여 줍니다. 이 저장소에는 공통 로그인 화면·로그인 완료 전달 브리지가 없으며, 실제 팀 로그인 담당자가 위 훅을 연결해야 합니다.
- 새 클라이언트는 `submitted`를 항상 명시합니다. 팝업 저장은 체크 여부의 boolean, 지원 완료 전환은 `true`, 문항 없이 저장할 때는 `essays: []`를 보냅니다. ① 확장은 사용자 승인 없이 본문·답변을 수집하거나 자동 전송하지 않습니다.
- 자동 테스트: `web/tests/unit/extension.spec.ts`는 Chrome 저장소 대역으로 공고 추정·토큰 저장·주소 권한·명시 submitted·401 상태와 토큰 경합을 검사합니다. `web/e2e/track-extension.spec.ts`는 팝업 DOM과 API·Chrome 대역으로 사용자 클릭 수집·기존 공고 제출 전환·401/재로그인·계정 전환을 검사합니다. 실제 Chrome 설치·권한·페이지 주입·Supabase/팀 로그인 연결은 검증하지 않았습니다.

## 회사·직무 추정 방식

`extract.js`가 `og:title`(없으면 `<title>`)을 읽어 `[회사] 제목`, `제목 | 회사 - 플랫폼` 같은 흔한 형식을 나눕니다. 사람인·원티드·잡코리아·LinkedIn 같은 플랫폼 이름과 "채용", "모집" 같은 꼬리말은 떼어 냅니다. 사이트마다 구조가 달라 틀릴 수 있으므로 저장 전에 사용자가 고칠 수 있게 했습니다.
