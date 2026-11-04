// 영상 지표·시선 보정이 함께 쓰는 작은 통계 함수. 입력 배열은 바꾸지 않는다.
// 빈 배열이면 둘 다 NaN이다: "표본이 없을 때"의 뜻(0, null, 판단 보류)은 호출한 쪽이 정한다

/** 중앙값(짝수 개면 가운데 두 값의 평균). 빈 배열이면 NaN */
export function median(xs: readonly number[]): number {
  if (!xs.length) return NaN;
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** nearest-rank 백분위수(q는 0~1): 작은 쪽부터 ceil(q·n)번째 값. 빈 배열이면 NaN */
export function nearestRank(xs: readonly number[], q: number): number {
  if (!xs.length) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.max(0, Math.ceil(q * s.length) - 1))];
}
