import { realpathSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, relative, resolve } from "node:path";

/** Resolve links before checking containment: a lexical /tmp path can point at real user data. */
export function isolatedTemporaryDirectory(path: string): string {
  const root = realpathSync(tmpdir());
  const canonical = realpathSync(resolve(path));
  const child = relative(root, canonical);
  if (!child || child.startsWith("..") || isAbsolute(child) || !statSync(canonical).isDirectory()) {
    throw new Error(`E2E 데이터는 임시 폴더(${root}) 안의 전용 디렉터리여야 해요`);
  }
  return canonical;
}
