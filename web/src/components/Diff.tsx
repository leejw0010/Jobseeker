/** 두 버전의 단어 단위 차이(LCS). 자소서 길이(수천 자) 정도면 충분히 빠르다. */
function tokenize(s: string) {
  return s.split(/(\s+)/).filter((t) => t.length);
}

export function diffTokens(a: string, b: string) {
  const x = tokenize(a);
  const y = tokenize(b);
  const n = x.length;
  const m = y.length;
  const dp: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { t: "same" | "add" | "del"; s: string }[] = [];
  let i = 0;
  let j = 0;
  const push = (t: "same" | "add" | "del", s: string) => {
    const last = out[out.length - 1];
    if (last && last.t === t) last.s += s;
    else out.push({ t, s });
  };
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      push("same", x[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) push("del", x[i++]);
    else push("add", y[j++]);
  }
  while (i < n) push("del", x[i++]);
  while (j < m) push("add", y[j++]);
  return out;
}

export default function Diff({ before, after }: { before: string; after: string }) {
  return (
    <div className="diff">
      {diffTokens(before, after).map((p, k) =>
        p.t === "same" ? <span key={k}>{p.s}</span> : p.t === "add" ? <ins key={k}>{p.s}</ins> : <del key={k}>{p.s}</del>,
      )}
    </div>
  );
}
