/** 상태·결과 칩(합격·불합격·진행중·보류) */
export function StatusChip({ status }: { status: string }) {
  const cls = status === "합격" ? "good" : status === "불합격" ? "bad" : status === "진행중" ? "accent" : "";
  return <span className={`chip ${cls}`}>{status}</span>;
}
