import { expect, test } from "@playwright/test";
import { createApiClient } from "../../src/api";

test.describe.configure({ mode: "serial" });
let original: typeof fetch;
test.beforeEach(() => { original = globalThis.fetch; });
test.afterEach(() => { globalThis.fetch = original; });

test("host supplies API origin and current access token without URL credentials", async () => {
  let seen: { url: string; init?: RequestInit } | undefined;
  globalThis.fetch = async (url, init) => { seen = { url: String(url), init }; return Response.json([]); };
  const client = createApiClient({ baseUrl: "https://api.example.test", getAccessToken: async () => "ephemeral-test-token" });
  await client.applications();
  expect(seen?.url).toBe("https://api.example.test/track/applications");
  expect(seen?.init?.headers).toMatchObject({ Authorization: "Bearer ephemeral-test-token" });
});

test("one host refresh retries a read but never repeats a write", async () => {
  let calls = 0, refreshes = 0;
  globalThis.fetch = async () => { calls++; return calls % 2 ? Response.json({detail:"expired"}, {status:401}) : Response.json([]); };
  const client = createApiClient({ baseUrl: "https://api.example.test", onUnauthorized: async () => { refreshes++; } });
  await client.applications();
  expect(calls).toBe(2); expect(refreshes).toBe(1);
  await expect(client.createApplication({company:"会社",position:"開発"})).rejects.toMatchObject({status:401});
  expect(calls).toBe(3); expect(refreshes).toBe(2);
});

test("account reset rejects a late response instead of showing the previous user's data", async () => {
  let finish!: (r: Response) => void;
  globalThis.fetch = () => new Promise<Response>(resolve => { finish = resolve; });
  const client = createApiClient({ baseUrl: "https://api.example.test" });
  const pending = client.applications();
  await Promise.resolve(); await Promise.resolve();
  client.resetSession();
  finish(Response.json([{id:"old-user-record"}]));
  await expect(pending).rejects.toMatchObject({name:"AbortError"});
});

test("account reset also rejects a response whose JSON body is still being read", async () => {
  let finish!: (value: unknown) => void;
  let reading!: () => void;
  const started = new Promise<void>(resolve => { reading = resolve; });
  globalThis.fetch = async () => ({ok:true,status:200,json:() => { reading(); return new Promise(resolve => { finish = resolve; }); }}) as Response;
  const client = createApiClient({baseUrl:"https://api.example.test"});
  const pending = client.applications();
  await started;
  client.resetSession();
  finish([{id:"previous-user"}]);
  await expect(pending).rejects.toMatchObject({name:"AbortError"});
});
