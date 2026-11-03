import { defineConfig } from "@playwright/test";

// 브라우저·서버 없이 도는 계산 테스트(영상 지표·시선 보정·회고 지표). 백엔드·웹 서버를 띄우지 않는다
export default defineConfig({
  testDir: "./tests/unit",
  fullyParallel: true,
  timeout: 15000,
  projects: [{ name: "unit" }],
});
