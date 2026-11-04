import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative, resolve } from "node:path";
import { BROWSER_API } from "./e2e/env";

// 녹음은 실행마다 새 임시 폴더에 둔다. 테스트가 동의를 철회(전체 녹음 삭제)하므로 개발용 backend/recordings/를 쓰면
// 그 폴더의 개발 사용자 녹음이 지워진다. 워커는 러너의 환경변수를 물려받아 같은 폴더를 본다
process.env.E2E_RECORDINGS_DIR ??= mkdtempSync(join(tmpdir(), "jobseeker-e2e-recordings-"));
const recordings = resolve(process.env.E2E_RECORDINGS_DIR);
const insideTmp = relative(resolve(tmpdir()), recordings);
if (!insideTmp || insideTmp.startsWith("..") || isAbsolute(insideTmp)) {
  throw new Error(`E2E_RECORDINGS_DIR는 임시 폴더(${tmpdir()}) 안이어야 해요: ${recordings}`);
}

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: "http://localhost:5179",
    trace: "retain-on-failure",
    launchOptions: {
      executablePath: process.env.CHROMIUM_EXECUTABLE_PATH || undefined,
      args: ["--no-sandbox", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
    },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    // 화면 크기만 휴대폰에 맞춘 Chromium이다. 모바일 Safari·실제 기기의 권한 동작은 검증하지 않는다
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
  webServer: [
    { command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 8011", cwd: "../backend",
      url: "http://127.0.0.1:8011/health", reuseExistingServer: false,
      // 가짜 마이크는 신호음만 내므로 실제 전사 모델을 돌리지 않는다(로컬 STT는 backend/tests/test_local_stt.py가 검사)
      env: { AUTH_DISABLED: "true", OPENAI_API_KEY: "", STT_PROVIDER: "off", SUPABASE_URL: "", SUPABASE_SERVICE_ROLE_KEY: "",
        DATABASE_URL: `sqlite:///${join(tmpdir(), `jobseeker-e2e-${process.pid}.db`)}`,
        RECORDINGS_DIR: recordings,
        CORS_ORIGINS: "http://localhost:5179,http://127.0.0.1:5179" } },
    { command: "npm run dev -- --host 127.0.0.1 --port 5179 --strictPort", url: "http://localhost:5179", reuseExistingServer: false,
      // 카메라 분석은 모델을 내려받지 않는 가짜 검출기로 돌린다(src/video/fakeDetector.ts)
      // 개발 전용 시선 실험실(/dev/gaze-lab)도 켠다(e2e/gaze-lab.spec.ts)
      env: { VITE_API_URL: BROWSER_API, VITE_E2E_FAKE_FACE: "true", VITE_GAZE_LAB: "true" } },
  ],
});
