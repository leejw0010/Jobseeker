import { expect, test } from "@playwright/test";
import { gazeFeatures } from "../../src/video/gaze/features";
import { aggregate, collect, evaluateRun, PROTOCOL } from "../../src/video/gaze/calibration";
import { fakeFrames, syntheticFace, syntheticRun, VIEW } from "../../src/video/gaze/synthetic";

test("gaze rejects bad resolution, nonfinite geometry and within-fixation resolution changes", () => {
  const points = syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0 });
  expect(gazeFeatures(points, 0, 480)).toEqual({ invalid: "invalid_resolution" });
  points[1].x = NaN;
  expect(gazeFeatures(points, 640, 480)).toEqual({ invalid: "nonfinite_geometry" });
  const frames = fakeFrames(3);
  frames[1].width = 1280;
  const d = collect(frames, PROTOCOL[0]);
  expect(d.invalid.resolution_changed).toBe(1);
  expect(d.samples).toHaveLength(2);
});

test("blink rejection retains held-out lens unknowns and reports diagnostics", () => {
  const run = syntheticRun({ noise: 0.0001, seed: 31 });
  const valLens = run.find((d) => d.fixation.id === "val-lens-forward")!;
  valLens.samples.forEach((s) => { s.f.open = 0; });
  const r = evaluateRun(run, VIEW);
  expect(r.g1.lensForward).toBe(0);
  expect(r.diag.lens.find((x) => x.id === "val-lens-forward")?.unknown).toBe(1);
  expect(r.diag.quality.rejected.blink).toBe(15);
  expect(aggregate(r)["diag.quality.rejected.blink"]).toBe(15);
});

test("all-blink held-out screen fixation makes G2 insufficient instead of improving its error", () => {
  const run = syntheticRun({ noise: 0.0001, seed: 32 });
  run.find((d) => d.fixation.id === "val-25-25")!.samples.forEach((s) => { s.f.open = 0; });
  const r = evaluateRun(run, VIEW);
  expect(r.g2.e50Px).toBeNull();
  expect(r.g2.verdict).not.toBe("pass");
  expect(r.diag.quality.rejected.blink).toBe(15);
});

test("blink contamination in training is excluded consistently with held-out evaluation", () => {
  const run = syntheticRun({ noise: 0.0001, seed: 33 });
  for (const d of run.filter((x) => x.fixation.role === "train")) {
    d.samples.push({ t: 1200, f: { ...d.samples[0].f, open: 0, ex: 999 } });
    d.frames++;
  }
  const r = evaluateRun(run, VIEW);
  expect(r.g2.e50Px!).toBeLessThan(60);
  expect(r.g1.verdict).toBe("pass");
  expect(r.diag.quality.rejected.blink).toBeGreaterThan(20);
});

test("pose flags and invalid reasons supplement existing lens OOD diagnostics", () => {
  const run = syntheticRun({ noise: 0.0001, seed: 34 });
  const d = run.find((x) => x.fixation.id === "val-lens-forward")!;
  d.samples.forEach((s) => { s.f.faceX += 0.3; });
  d.invalid.invalid_resolution = 2;
  d.frames += 2;
  const r = evaluateRun(run, VIEW);
  expect(r.diag.quality.poseFlags).toBeGreaterThanOrEqual(15);
  expect(r.diag.quality.rejected.invalid_resolution).toBe(2);
  expect(r.diag.quality.accepted).toBeLessThan(r.diag.quality.total);
});

test("nonfinite timing and overflowed geometric arithmetic do not reach calibration", () => {
  const frames = fakeFrames(3);
  frames[0].t = NaN;
  frames[1].points![1].x = Number.MAX_VALUE;
  const d = collect(frames, PROTOCOL[0]);
  expect(d.invalid.nonfinite_geometry).toBe(2);
  expect(d.samples).toHaveLength(1);
});

import * as quality from "../../src/video/gaze/quality";
test("closed-eye baseline drift is unavailable instead of an infinite percentage", () => {
  const run = syntheticRun({ noise: 0.0001, seed: 31 });
  run.filter(d => d.fixation.role === "train" && d.fixation.target === "lens" && d.fixation.pose === "forward")
    .forEach(d => d.samples.forEach(s => { s.f.open = 0; }));
  const result = evaluateRun(run, VIEW);
  expect(result.diag.drift.open).toBeNull();
});
test("calibration invalidation distinguishes viewport from camera resolution changes and stays invalid", () => {
  expect(typeof quality.createCalibrationGuard).toBe("function");
  const camera = quality.createCalibrationGuard("view1", { width: 640, height: 480 });
  expect(camera.check("view1", { width: 640, height: 480 })).toBeNull();
  expect(camera.check("view1", { width: 1280, height: 720 })).toBe("resolution_changed");
  expect(camera.check("view1", { width: 640, height: 480 })).toBe("resolution_changed");
  const viewport = quality.createCalibrationGuard("view1");
  expect(viewport.check("view2")).toBe("viewport_changed");
});
