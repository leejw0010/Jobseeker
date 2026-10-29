import { expect, test } from "@playwright/test";
import {
  MAX_GAP_MS, MIN_HEAD_SAMPLES, SAMPLE_MS, combineSummaries, faceFeatures, summarizeSegment, type FaceSample, type Point,
} from "../src/video/metrics";

// 브라우저 없이 계산만 확인한다. 화면 크기와 상관없으므로 desktop 프로젝트에서만 돈다
test.beforeEach(({}, testInfo) => test.skip(testInfo.project.name !== "desktop"));

/** 가운데 얼굴(폭 0.2, 이마–턱 0.35). dx·dy만큼 코끝을 옮기고, offsetX만큼 얼굴 전체를 옮긴다 */
function face(dx = 0, dy = 0, offsetX = 0): Point[] {
  const pts: Point[] = Array.from({ length: 478 }, () => ({ x: 0.5 + offsetX, y: 0.5 }));
  pts[1] = { x: 0.5 + offsetX + dx, y: 0.5 + dy };
  pts[10] = { x: 0.5 + offsetX, y: 0.35 };
  pts[152] = { x: 0.5 + offsetX, y: 0.7 };
  pts[234] = { x: 0.4 + offsetX, y: 0.5 };
  pts[454] = { x: 0.6 + offsetX, y: 0.5 };
  return pts;
}
const samples = (list: (Point[] | null)[], step = SAMPLE_MS): FaceSample[] => list.map((p, i) => ({ t: i * step, ...faceFeatures(p) }));
const repeat = <T,>(n: number, v: T) => Array.from({ length: n }, () => v);

test("faceFeatures classifies frames and gives ratios relative to face size", () => {
  expect(faceFeatures(null)).toEqual({ state: "none" });
  const centered = faceFeatures(face());
  expect(centered.state).toBe("in");
  expect(centered.yaw).toBeCloseTo(0);
  expect(centered.pitch).toBeCloseTo(0.15 / 0.35);
  expect(faceFeatures(face(0.04)).yaw).toBeCloseTo(0.2);
  expect(faceFeatures(face(0, 0, 0.45)).state).toBe("edge"); // 오른쪽 가장자리가 1을 넘음
});

test("summarizeSegment measures detection, off-screen time and episodes", () => {
  // 3초 정면, 2초 얼굴 없음, 0.5초 가장자리, 0.25초 정면
  const s = summarizeSegment(samples([...repeat(12, face()), ...repeat(8, null), ...repeat(2, face(0, 0, 0.45)), face()]));
  expect(s.samples).toBe(23);
  expect(s.totalMs).toBe(23 * SAMPLE_MS);
  expect(s.detectedMs).toBe(15 * SAMPLE_MS);
  expect(s.offMs).toBe(10 * SAMPLE_MS);
  expect(s.offEpisodes).toBe(1);
  expect(s.longestOffMs).toBe(10 * SAMPLE_MS);
  // 1초보다 짧게 벗어난 것은 횟수로 세지 않는다
  expect(summarizeSegment(samples([...repeat(10, face()), null, null, ...repeat(10, face())])).offEpisodes).toBe(0);
});

test("head turn and head-down are measured relative to the answer's median", () => {
  // 평소에 살짝 왼쪽을 보고 있어도(dx=-0.02) 그것이 기준이다. 4표본만 크게 돌리고 3표본만 숙임
  const list = [...repeat(20, face(-0.02)), ...repeat(4, face(0.03)), ...repeat(3, face(-0.02, 0.04))];
  const s = summarizeSegment(samples(list));
  expect(s.headMs).toBe(27 * SAMPLE_MS);
  expect(s.turnedMs).toBe(4 * SAMPLE_MS);
  expect(s.downMs).toBe(3 * SAMPLE_MS);
  // 고개를 드는 쪽(dy<0)은 숙임으로 세지 않는다
  expect(summarizeSegment(samples([...repeat(20, face()), ...repeat(3, face(0, -0.04))])).downMs).toBe(0);
});

test("too few in-frame samples leave head metrics empty, and long gaps are capped", () => {
  expect(summarizeSegment(samples(repeat(MIN_HEAD_SAMPLES - 1, face()))).headMs).toBe(0);
  const gap = summarizeSegment(samples([face(), face()], 5000)); // 탭이 숨겨져 5초씩 벌어진 경우
  expect(gap.totalMs).toBe(MAX_GAP_MS + SAMPLE_MS);
  expect(summarizeSegment([]).totalMs).toBe(0);
});

test("combineSummaries adds durations and keeps the longest off-screen stretch", () => {
  const a = summarizeSegment(samples([...repeat(10, face()), ...repeat(8, null)]));
  const b = summarizeSegment(samples([...repeat(10, face()), ...repeat(12, null)]));
  const all = combineSummaries([a, b]);
  expect(all.totalMs).toBe(a.totalMs + b.totalMs);
  expect(all.offEpisodes).toBe(2);
  expect(all.longestOffMs).toBe(12 * SAMPLE_MS);
  expect(all.headMs).toBe(a.headMs + b.headMs);
});
