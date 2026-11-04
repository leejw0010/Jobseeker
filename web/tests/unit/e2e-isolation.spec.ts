import { test, expect } from "@playwright/test";
import { mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { isolatedTemporaryDirectory } from "../../e2e/isolation";

test("E2E storage accepts a real temporary directory and rejects a symlink escaping it", () => {
  const folder = mkdtempSync(join(tmpdir(), "jobseeker-isolation-test-"));
  try {
    expect(isolatedTemporaryDirectory(folder)).toBe(folder);
    const link = join(folder, "outside");
    symlinkSync("/usr", link);
    expect(() => isolatedTemporaryDirectory(link)).toThrow(/임시 폴더/);
    expect(() => isolatedTemporaryDirectory(tmpdir())).toThrow(/임시 폴더/);
  } finally { rmSync(folder, { recursive: true, force: true }); }
});

test("E2E storage rejects missing directories before any backend can start", () => {
  const folder = mkdtempSync(join(tmpdir(), "jobseeker-isolation-test-"));
  rmSync(folder, { recursive: true });
  expect(() => isolatedTemporaryDirectory(folder)).toThrow();
});
