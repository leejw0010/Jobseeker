import { expect, test } from "@playwright/test";
import * as voice from "../../src/delivery/voice";
const samples = (energies: number[]) => energies.map((rms, i) => ({ t: i / 10, rms }));
const fixture = () => samples([...Array(20).fill(0.003), ...Array(20).fill(0.08), ...Array(25).fill(0.003), ...Array(35).fill(0.09)]);

test("energy candidates separate total pace, active pace and observed pauses", () => {
  expect(typeof voice.summarizeVoice).toBe("function");
  const s = voice.summarizeVoice(fixture(), 10, "어, 저희는 음 문제를 해결했습니다");
  expect(s.quality).toBe("usable");
  expect(s.analyzedSec).toBeCloseTo(10);
  expect(s.coverage).toBeCloseTo(1);
  expect(s.activeCandidateSec).toBeCloseTo(5.5);
  expect(s.pauseCount).toBe(2);
  expect(s.longPauseCount).toBe(2);
  expect(s.longestPauseSec).toBeCloseTo(2.5);
  expect(s.syllables).toBe(14);
  expect(s.totalPacePerMin).toBeCloseTo(84);
  expect(s.silenceCandidateSec).toBeCloseTo(4.5);
  expect(s.silenceCandidateRatio).toBeCloseTo(0.45);
  expect(s.activeCandidatePacePerMin).toBeCloseTo(840 / 5.5);
  expect(s.fillers).toEqual([{ token: "어", count: 1 }, { token: "음", count: 1 }]);
  expect(JSON.stringify(s)).not.toMatch(/"t"|"rms"/);
});

test("silence, constant energy and clipping cannot become speech measurements", () => {
  const silent = voice.summarizeVoice(samples(Array(100).fill(0)), 10, "말을 했습니다");
  expect(silent.quality).toBe("insufficient");
  expect(silent.activeCandidateSec).toBeNull();
  expect(silent.activeCandidatePacePerMin).toBeNull();
  const constant = voice.summarizeVoice(samples(Array(100).fill(0.1)), 10);
  expect(constant.quality).toBe("unreliable");
  expect(constant.reasons).toContain("constant_energy");
  const clipped = voice.summarizeVoice(fixture().map((x) => ({ ...x, clipped: true })), 10);
  expect(clipped.quality).toBe("unreliable");
  expect(clipped.pauseCount).toBeNull();
});

test("gaps, invalid values and partial coverage remain unknown instead of silence", () => {
  const s = voice.summarizeVoice(fixture().filter((x) => x.t < 2 || x.t >= 8), 10);
  expect(s.quality).toBe("unreliable");
  expect(s.coverage).toBeLessThan(0.5);
  expect(s.reasons).toContain("partial_coverage");
  expect(s.pauseCount).toBeNull();
  const invalid = voice.summarizeVoice([{ t: NaN, rms: 0.1 }, { t: 0, rms: Infinity }], NaN);
  expect(invalid.quality).toBe("unavailable");
  expect(Object.values(invalid).filter((x) => typeof x === "number").every(Number.isFinite)).toBe(true);
});

test("transcript filler candidates use word boundaries and have no acoustic timestamps", () => {
  const s = voice.withVoiceTranscript(voice.summarizeVoice(fixture(), 10), "어머니는 저희에게 음악을 가르쳤습니다. 음, 어… 음");
  expect(s.fillers).toEqual([{ token: "음", count: 2 }, { token: "어", count: 1 }]);
  expect(s.fillers.every((x) => Object.keys(x).sort().join() === "count,token")).toBe(true);
});

test("revision storage refuses replaced recordings and supports per-answer clearing", () => {
  const s = voice.summarizeVoice(fixture(), 10);
  voice.saveVoiceSegment("s", "a", s, "r1");
  expect(voice.getVoiceSegment("s", "a", "r1")?.quality).toBe("usable");
  voice.saveVoiceSegment("s", "a", s, "r2");
  expect(voice.getVoiceSegment("s", "a", "r1")).toBeUndefined();
  voice.clearVoiceSegment("s", "a");
  expect(voice.getVoiceSegment("s", "a", "r2")).toBeUndefined();
  voice.saveVoiceSegment("s", "b", s, "r1");
  voice.clearSessionVoice("s");
  expect(voice.getVoiceSegment("s", "b", "r1")).toBeUndefined();
});

test("bounded sampling retains a finite coverage summary after its budget is exhausted", () => {
  const buffer = voice.createVoiceSampler(3);
  for (let i = 0; i < 100; i++) buffer.add({ t: i / 10, rms: i % 2 ? 0.08 : 0.003 });
  expect(buffer.snapshot()).toHaveLength(3);
  expect(voice.summarizeVoice(buffer.snapshot(), 10).quality).toBe("unreliable");
});

test("whole-recording syllable pace survives optional energy failure but short and empty text do not acquire pace", () => {
  const s = voice.summarizeVoice([], 10, "가나다 ABC 12");
  expect(s.syllables).toBe(8);
  expect(s.quality).toBe("unavailable");
  expect(s.totalPacePerMin).toBe(48);
  expect(s.activeCandidatePacePerMin).toBeNull();
  expect(s.silenceCandidateRatio).toBeNull();
  expect(voice.summarizeVoice([], 4, "가나다").totalPacePerMin).toBeNull();
  expect(voice.summarizeVoice([], 10).totalPacePerMin).toBeNull();
});

test("withdrawal can clear voice summaries across every session", () => {
  expect(typeof voice.clearAllVoice).toBe("function");
  const s = voice.summarizeVoice([], 10);
  voice.saveVoiceSegment("s1", "a", s, "r1");
  voice.saveVoiceSegment("s2", "b", s, "r2");
  voice.clearAllVoice();
  expect(voice.getVoiceSegment("s1", "a", "r1")).toBeUndefined();
  expect(voice.getVoiceSegment("s2", "b", "r2")).toBeUndefined();
});

test("even a short missing window is not accepted as a reliable continuous candidate measurement", () => {
  const s = voice.summarizeVoice(fixture().filter((x) => x.t < 4 || x.t >= 4.5), 10);
  expect(s.coverage).toBeGreaterThan(0.9);
  expect(s.quality).toBe("unreliable");
  expect(s.reasons).toContain("sampling_gap");
  expect(s.activeCandidateSec).toBeNull();
  expect(s.pauseCount).toBeNull();
});

test("nonfinite timestamps cannot hide invalid observations inside otherwise good coverage", () => {
  const s = voice.summarizeVoice([...fixture(), { t: NaN, rms: 0.08 }], 10);
  expect(s.quality).toBe("unreliable");
  expect(s.reasons).toContain("invalid_timestamp");
  expect(s.activeCandidateSec).toBeNull();
});
