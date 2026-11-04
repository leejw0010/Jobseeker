import { expect, test } from "@playwright/test";
import {
  CORE_LANDMARKS, MAX_GAP_MS, MIN_HEAD_SAMPLES, SAMPLE_MS, combineSummaries, edgeLabel, faceFeatures, summarizeSegment,
  type FaceSample, type Point,
} from "../../src/video/metrics";


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

test("summarizeSegment separates none and edge time without overlap", () => {
  // 3초 정면, 2초 얼굴 없음, 0.5초 가장자리, 0.25초 정면
  const s = summarizeSegment(samples([...repeat(12, face()), ...repeat(8, null), ...repeat(2, face(0, 0, 0.45)), face()]));
  expect(s.samples).toBe(23);
  expect(s.analyzedMs).toBe(23 * SAMPLE_MS);
  expect(s.inMs).toBe(13 * SAMPLE_MS);
  expect(s.edgeMs).toBe(2 * SAMPLE_MS);
  expect(s.noneMs).toBe(8 * SAMPLE_MS);
  expect(s.detectedMs).toBe(15 * SAMPLE_MS);
  expect(s.inMs + s.edgeMs + s.noneMs).toBe(s.analyzedMs);
  expect(s.noneEpisodes).toBe(1);
  expect(s.longestNoneMs).toBe(8 * SAMPLE_MS);
  expect(s.answerMs).toBe(s.analyzedMs); // 답변 시각을 모르면 같다
  // 1초보다 짧게 찾지 못한 것은 횟수로 세지 않는다
  expect(summarizeSegment(samples([...repeat(10, face()), null, null, ...repeat(10, face())])).noneEpisodes).toBe(0);
});

test("edge-only answer is fully detected with zero not-found time", () => {
  // 예전 정의에서는 이 답변이 '검출 100%, 화면을 벗어난 시간 100%'로 함께 나왔다
  const s = summarizeSegment(samples(repeat(20, face(0, 0, 0.45))));
  expect(s.detectedMs).toBe(s.analyzedMs);
  expect(s.noneMs).toBe(0);
  expect(s.edgeMs).toBe(s.analyzedMs);
  expect(s.noneEpisodes).toBe(0);
});

test("flickering none is counted as time but not as episodes", () => {
  const s = summarizeSegment(samples(Array.from({ length: 40 }, (_, i) => (i % 4 === 3 ? null : face()))));
  expect(s.noneMs).toBe(10 * SAMPLE_MS);
  expect(s.noneEpisodes).toBe(0);
});

test("leaving and returning: edge around a long none run", () => {
  const list = [...repeat(8, face()), ...repeat(2, face(0, 0, 0.45)), ...repeat(24, null), ...repeat(2, face(0, 0, 0.45)), ...repeat(8, face())];
  const s = summarizeSegment(samples(list));
  expect(s.noneMs).toBe(24 * SAMPLE_MS);
  expect(s.noneEpisodes).toBe(1);
  expect(s.longestNoneMs).toBe(24 * SAMPLE_MS);
  expect(s.edgeMs).toBe(4 * SAMPLE_MS);
});

test("answer time vs analyzed time: hidden tab gap, last sample clipped, early stop", () => {
  // 탭이 가려져 표본 사이가 5초 벌어짐: 1초만 분석한 것으로 센다. 마지막 표본은 답변 끝에서 잘린다
  const gap = summarizeSegment([{ t: 0, state: "in" }, { t: 5000, state: "in" }], { start: 0, end: 5100 });
  expect(gap.answerMs).toBe(5100);
  expect(gap.analyzedMs).toBe(MAX_GAP_MS + 100);
  // samples stop early inside the span(답변 도중 카메라를 끔)
  const early = summarizeSegment(samples(repeat(8, face())), { start: 0, end: 10_000 });
  expect(early.analyzedMs).toBe(7 * SAMPLE_MS + MAX_GAP_MS);
  expect(early.answerMs).toBe(10_000);
  // empty segment with span(카메라 화면이 준비되기 전에 답변을 마침)
  const empty = summarizeSegment([], { start: 0, end: 3000 });
  expect(empty).toMatchObject({ answerMs: 3000, analyzedMs: 0, noneMs: 0, samples: 0 });
  expect(summarizeSegment([]).analyzedMs).toBe(0);
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
  expect(gap.analyzedMs).toBe(MAX_GAP_MS + SAMPLE_MS);
});

test("combineSummaries adds durations and keeps the longest not-found stretch", () => {
  const a = summarizeSegment(samples([...repeat(10, face()), ...repeat(8, null)]));
  const b = summarizeSegment(samples([...repeat(10, face()), ...repeat(12, null)]));
  const all = combineSummaries([a, b]);
  expect(all.analyzedMs).toBe(a.analyzedMs + b.analyzedMs);
  expect(all.answerMs).toBe(a.answerMs + b.answerMs);
  expect(all.noneMs).toBe(20 * SAMPLE_MS);
  expect(all.noneEpisodes).toBe(2);
  expect(all.longestNoneMs).toBe(12 * SAMPLE_MS);
  expect(all.headMs).toBe(a.headMs + b.headMs);
});

/** 실제 메시처럼 이마 위(10)·턱(152)·양 볼(234·454)을 가장 바깥에 두고, 핵심 부위(눈·코·입)는 얼굴 안쪽에 둔 얼굴 */
function meshFace(topY = 0.3, chinY = 0.75, leftX = 0.38, rightX = 0.62): Point[] {
  const pts: Point[] = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5 }));
  CORE_LANDMARKS.forEach((i, k) => { pts[i] = { x: 0.43 + (k % 3) * 0.07, y: 0.42 + Math.floor(k / 3) * 0.08 }; });
  pts[10] = { x: 0.5, y: topY };
  pts[152] = { x: 0.5, y: chinY };
  pts[234] = { x: leftX, y: 0.5 };
  pts[454] = { x: rightX, y: 0.5 };
  return pts;
}

test("forehead beyond the top edge with core features inside is edge with overshoot", () => {
  const f = faceFeatures(meshFace(-0.02));
  expect(f.state).toBe("edge");
  expect(f.coreInside).toBe(true);
  expect(f.overshoot!.top).toBeCloseTo(0.02);
  expect(f.overshoot).toMatchObject({ bottom: 0, left: 0, right: 0 });
  const inside = faceFeatures(meshFace());
  expect(inside.state).toBe("in");
  expect(inside.overshoot).toBeUndefined(); // in은 예전과 같은 값만 돌려준다
  expect(inside.coreInside).toBeUndefined();
});

test("edge label lists every crossed side, mirrored", () => {
  expect(edgeLabel({ top: 0.02, bottom: 0, left: 0, right: 0 })).toBe("얼굴 위쪽이 화면 밖에 있어요");
  // 미리보기는 좌우 반전이라 원본의 왼쪽(x<0)은 화면 오른쪽이다
  expect(edgeLabel({ top: 0.02, bottom: 0, left: 0.05, right: 0 })).toBe("얼굴 위쪽·오른쪽이 화면 밖에 있어요");
  expect(edgeLabel({ top: 0, bottom: 0.03, left: 0, right: 0.04 })).toBe("얼굴 아래쪽·왼쪽이 화면 밖에 있어요");
  // 여유(EDGE_MARGIN) 안쪽으로만 넘은 쪽은 빼고, 실제로 edge를 만든 쪽만 알린다
  expect(edgeLabel({ top: 0.005, bottom: 0, left: 0, right: 0.02 })).toBe("얼굴 왼쪽이 화면 밖에 있어요");
  expect(edgeLabel({ top: 0, bottom: 0, left: 0, right: 0 })).toBe("얼굴 일부가 화면 밖에 있어요");
});

test("short landmark list: coreInside is false without throwing", () => {
  const pts = Array.from({ length: 20 }, () => ({ x: 0.5, y: 0.5 }));
  pts[0] = { x: 0.5, y: -0.05 };
  expect(faceFeatures(pts)).toMatchObject({ state: "edge", coreInside: false });
});

test("classification is unchanged for the existing fixtures", () => {
  expect(faceFeatures(face()).state).toBe("in");
  expect(faceFeatures(face(0, 0, 0.45)).state).toBe("edge");
  expect(faceFeatures(face(0, 0, 0.505)).state).toBe("edge");
  expect(faceFeatures(face(0, 0, 0.405)).state).toBe("in"); // 오른쪽 볼이 1.005: 여유(0.01) 안
  expect(faceFeatures(null)).toEqual({ state: "none" });
  expect(faceFeatures([])).toEqual({ state: "none" });
});

test("a long unanalyzed gap closes the not-found run instead of merging both sides", () => {
  // 얼굴 없음 1.25초(마지막 표본은 MAX_GAP_MS까지만 셈) → 5초 넘게 분석 못 함 → 다시 얼굴 없음 1초
  const none = (t: number): FaceSample => ({ t, state: "none" });
  const s = [none(0), none(250), none(6000), none(6250), none(6500), none(6750)];
  const out = summarizeSegment(s, { start: 0, end: 7000 });
  expect(out.noneMs).toBe(250 + MAX_GAP_MS + 1000);
  expect(out.noneEpisodes).toBe(2);
  expect(out.longestNoneMs).toBe(250 + MAX_GAP_MS);
});
