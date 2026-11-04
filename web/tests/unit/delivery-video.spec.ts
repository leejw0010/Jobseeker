import { expect, test } from "@playwright/test";
import * as metrics from "../../src/video/metrics";

test("nonfinite face points cannot be classified as an in-frame face", () => {
  expect(metrics.faceFeatures([{ x: NaN, y: 0.5 }]).state).toBe("none");
  expect(metrics.faceFeatures([{ x: 0.5, y: Infinity }]).state).toBe("none");
});

test("video intervals are clipped to answer bounds and nonfinite samples stay unknown", () => {
  const s = metrics.summarizeSegment([
    { t: -100, state: "in" }, { t: 100, state: "in", yaw: NaN, pitch: Infinity },
    { t: NaN, state: "in" }, { t: 200, state: "none" }, { t: 1000, state: "edge" },
  ], { start: 0, end: 500 });
  expect(s.answerMs).toBe(500);
  expect(s.analyzedMs).toBe(500);
  expect(s.inMs).toBe(200);
  expect(s.noneMs).toBe(300);
  expect(s.edgeMs).toBe(0);
  expect(s.headMs).toBe(0);
  expect(Object.values(s).every(Number.isFinite)).toBe(true);
});

test("diagnostics distinguish unanalysed coverage from face not found", () => {
  expect(typeof metrics.videoDiagnostics).toBe("function");
  const s = metrics.summarizeSegment([{ t: 2000, state: "none" }], { start: 0, end: 5000 });
  const d = metrics.videoDiagnostics(s);
  expect(d.unanalysedMs).toBe(4000);
  expect(d.coverage).toBe(0.2);
  expect(d.quality).toBe("partial");
  expect(d.comments.join(" ")).toContain("분석하지 못한");
  expect(d.comments.join(" ")).toContain("조명");
});

test("video revision replacement and clearing retain the legacy save/read signatures", () => {
  const s = metrics.summarizeSegment([]);
  metrics.saveVideoSegment("session", "answer", s);
  expect(metrics.sessionVideo("session")?.get("answer")).toEqual(s);
  expect(typeof metrics.getVideoSegments).toBe("function");
  expect(metrics.getVideoSegments("session", "answer", "r1")).toBeUndefined();
  metrics.saveVideoSegment("session", "answer", s, "r1");
  expect(metrics.getVideoSegments("session", "answer", "r1")).toEqual(s);
  metrics.saveVideoSegment("session", "answer", s, "r2");
  expect(metrics.getVideoSegments("session", "answer", "r1")).toBeUndefined();
  metrics.clearVideoSegment("session", "answer");
  expect(metrics.getVideoSegments("session", "answer", "r2")).toBeUndefined();
  metrics.clearSessionVideo("session");
  expect(metrics.sessionVideo("session")).toBeUndefined();
});

test("invalid time spans cannot poison video summaries or relative head metrics", () => {
  const s = metrics.summarizeSegment(Array.from({ length: 10 }, (_, i) => ({ t: i * 250, state: "in", yaw: NaN, pitch: Infinity })), { start: NaN, end: Infinity });
  expect(Object.values(s).every(Number.isFinite)).toBe(true);
  expect(s.headMs).toBe(0);
});

test("bounded face sampling leaves the remainder unanalysed instead of retaining unlimited observations", () => {
  expect(typeof metrics.createFaceSampler).toBe("function");
  const buffer = metrics.createFaceSampler(3);
  for (let i = 0; i < 20; i++) buffer.add({ t: i * 250, state: "in" });
  expect(buffer.snapshot()).toHaveLength(3);
  const d = metrics.videoDiagnostics(metrics.summarizeSegment(buffer.snapshot(), { start: 0, end: 5000 }));
  expect(d.coverage).toBe(0.3);
  expect(d.unanalysedMs).toBe(3500);
});

test("withdrawal clears all video sessions and their recording revisions", () => {
  expect(typeof metrics.clearAllVideo).toBe("function");
  const s = metrics.summarizeSegment([]);
  metrics.saveVideoSegment("s1", "a", s, "r1");
  metrics.saveVideoSegment("s2", "b", s, "r2");
  metrics.clearAllVideo();
  expect(metrics.sessionVideo("s1")).toBeUndefined();
  expect(metrics.getVideoSegments("s2", "b", "r2")).toBeUndefined();
});
