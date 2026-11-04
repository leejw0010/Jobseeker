// e2e 공통 주소·경로. playwright.config.ts와 spec이 같은 값을 쓴다
/** 테스트 코드(request 픽스처)가 부르는 백엔드 주소. 서버는 127.0.0.1에 묶인다 */
export const API = "http://127.0.0.1:8011";
/** 웹 앱(VITE_API_URL)이 브라우저에서 부르는 백엔드 주소. 페이지 요청을 거를 때는 이 값을 쓴다 */
export const BROWSER_API = "http://localhost:8011";
/** 백엔드 개발 모드의 고정 사용자(backend/app/auth.py DEV_USER_ID) */
export const DEV_USER_ID = "00000000-0000-0000-0000-000000000001";

/** 이번 실행의 임시 녹음 폴더. playwright.config.ts가 만들고 워커는 환경변수로 물려받는다 */
export function recordingsDir(): string {
  const dir = process.env.E2E_RECORDINGS_DIR;
  if (!dir) throw new Error("E2E_RECORDINGS_DIR가 없어요: playwright.config.ts로 실행해 주세요");
  return dir;
}

/** 문서용 스크린샷 경로. 기본은 테스트 산출물(test-results/)이고, UPDATE_DOC_SCREENSHOTS=1일 때만 docs/screenshots/를 덮어쓴다 */
export function docScreenshotPath(name: string, outputPath: (file: string) => string): string {
  return process.env.UPDATE_DOC_SCREENSHOTS === "1" ? `../docs/screenshots/${name}.png` : outputPath(`${name}.png`);
}
