import { expect, test } from "@playwright/test";
import { median, nearestRank } from "../../src/video/stats";

test("median sorts a copy and averages the middle pair", () => {
  const xs = [3, 1, 2];
  expect(median(xs)).toBe(2);
  expect(xs).toEqual([3, 1, 2]);
  expect(median([4, 1, 3, 2])).toBe(2.5);
});

test("nearestRank picks the ceil(q·n)-th smallest value", () => {
  const xs = [50, 10, 40, 20, 30];
  expect(nearestRank(xs, 0.5)).toBe(30);
  expect(nearestRank(xs, 0.95)).toBe(50);
  expect(nearestRank(xs, 0)).toBe(10);
  expect(nearestRank(xs, 1)).toBe(50);
});

test("empty input is NaN for both, so callers must decide what an empty window means", () => {
  expect(median([])).toBeNaN();
  expect(nearestRank([], 0.5)).toBeNaN();
});
