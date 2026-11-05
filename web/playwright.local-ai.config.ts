// Protocol integration only: isolated temporary data, a loopback fixture, no paid API.
import { defineConfig } from '@playwright/test';
import base from './playwright.config';
const servers = Array.isArray(base.webServer) ? base.webServer : [base.webServer!];
export default defineConfig({
  ...base,
  testDir: './e2e-local-ai',
  outputDir: './test-results/local-ai',
  webServer: [
    {command:'python evals/local_openai_fixture.py --port 8012',cwd:'../backend',url:'http://127.0.0.1:8012/health',reuseExistingServer:false},
    ...servers.map((server,index) => index === 0 ? {...server,env:{...server.env,
      OPENAI_API_KEY:'local-protocol-fixture', OPENAI_BASE_URL:'http://127.0.0.1:8012/v1',
      PRACTICE_COMPETENCY_EVIDENCE_ENABLED:'true'}} : server),
  ],
});
