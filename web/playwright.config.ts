import { defineConfig, devices } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

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
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
  webServer: [
    { command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 8011", cwd: "../backend",
      url: "http://127.0.0.1:8011/health", reuseExistingServer: false,
      env: { AUTH_DISABLED: "true", OPENAI_API_KEY: "", SUPABASE_URL: "", SUPABASE_SERVICE_ROLE_KEY: "",
        DATABASE_URL: `sqlite:///${join(tmpdir(), `jobseeker-e2e-${process.pid}.db`)}`,
        CORS_ORIGINS: "http://localhost:5179,http://127.0.0.1:5179" } },
    { command: "npm run dev -- --host 127.0.0.1 --port 5179 --strictPort", url: "http://localhost:5179", reuseExistingServer: false,
      // 카메라 분석은 모델을 내려받지 않는 가짜 검출기로 돌린다(src/video/fakeDetector.ts)
      env: { VITE_API_URL: "http://localhost:8011", VITE_E2E_FAKE_FACE: "true" } },
  ],
});
