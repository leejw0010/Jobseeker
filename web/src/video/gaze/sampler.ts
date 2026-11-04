/** 표본 주기와 성능 통계. 검출은 기존 검출기 하나로 하고, 주기만 바꾼다(설계 10절). */
import { SAMPLE_MS } from "../metrics";
import { RATE_POLICY, type Rate } from "./constants";
import { nearestRank } from "../stats";

/** 한 번의 검출 결과. 특징점은 이 탭 메모리에서만 쓰고 저장·전송하지 않는다 */
export type Frame = {
  t: number;
  points: { x: number; y: number; z?: number }[] | null;
  width: number;
  height: number;
  detectMs: number;
};

export type RateSnapshot = {
  targetHz: number;
  achievedHz: number;
  detectP50: number;
  detectP95: number;
  /** 최근 창에서 검출이 메인 스레드를 차지한 비율(%) */
  busyPct: number;
  /** 예정 시각보다 늦게 돈 정도(ms)의 p95. 메인 스레드가 바쁜지 보는 지표 */
  lagP95: number;
  longTasks: number;
};

/** D 요약용 250ms 격자: 아직 표본을 받지 않은 칸의 첫 표본만 받는다(시간 기준이라 공백 뒤에도 다음 칸의 첫 표본을 받는다).
 *  검출을 초당 10·15회로 해도 D는 평균 초당 4회 표본을 받아 지금과 같은 요약을 낸다 */
export function createDGrid(periodMs: number = SAMPLE_MS) {
  let lastCell = -Infinity;
  return {
    accept(t: number): boolean {
      const cell = Math.floor(t / periodMs);
      if (cell <= lastCell) return false;
      lastCell = cell;
      return true;
    },
  };
}

type Entry = { t: number; detectMs: number; lagMs: number; longTask?: boolean };

// 표본이 없으면 0으로 보고한다(최근 10초에 측정한 것이 없음)
const rank = (xs: number[], q: number) => (xs.length ? nearestRank(xs, q) : 0);

/** 최근 windowMs 동안의 검출 시간·지연·긴 작업 통계 */
export function createRateStats(windowMs: number = RATE_POLICY.windowMs) {
  let entries: Entry[] = [];
  return {
    add(e: Entry) {
      entries.push(e);
      const newest = Math.max(...entries.map((x) => x.t));
      entries = entries.filter((x) => x.t >= newest - windowMs);
    },
    snapshot(targetHz: number): RateSnapshot {
      const frames = entries.filter((e) => !e.longTask);
      const ts = frames.map((e) => e.t);
      const span = frames.length >= 2 ? Math.max(...ts) - Math.min(...ts) : 0;
      const covered = frames.length >= 2 ? span + span / (frames.length - 1) : 0; // 마지막 표본이 대표하는 한 칸까지
      const detect = frames.map((e) => e.detectMs);
      return {
        targetHz,
        achievedHz: span > 0 ? ((frames.length - 1) / span) * 1000 : 0,
        detectP50: rank(detect, 0.5),
        detectP95: rank(detect, 0.95),
        busyPct: covered > 0 ? (detect.reduce((a, b) => a + b, 0) / covered) * 100 : 0,
        lagP95: rank(frames.map((e) => e.lagMs), 0.95),
        longTasks: entries.filter((e) => e.longTask).length,
      };
    },
  };
}

const ORDER: Rate[] = [4, 10, 15];

/** 다음 표본 주기. 메인 스레드가 힘들면 한 단계 내리고, healthySinceMs 동안 괜찮았으면 한 단계 올린다.
 *  목표(target)를 넘지 않고 초당 4회 아래로 내리지 않는다. 높은 주기를 강제하지 않는다 */
export function nextRate(current: Rate, target: Rate, s: RateSnapshot, healthySinceMs: number): Rate {
  const i = ORDER.indexOf(current);
  const cap = ORDER.indexOf(target);
  const overloaded = s.busyPct > RATE_POLICY.busyPct || s.longTasks >= RATE_POLICY.longTasks || s.lagP95 > RATE_POLICY.lagP95;
  if (overloaded) return ORDER[Math.max(0, Math.min(i, cap) - 1)];
  if (i > cap) return target;
  if (healthySinceMs >= RATE_POLICY.healthyMs && i < cap) return ORDER[i + 1];
  return current;
}
