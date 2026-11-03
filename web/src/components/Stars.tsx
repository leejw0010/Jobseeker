/** 자기 평가 별점. disabled면(저장 중 등) 누를 수 없다 */
export default function Stars({ value, onChange, disabled = false }: { value: number | null; onChange: (v: number) => void; disabled?: boolean }) {
  return (
    <span className="stars" role="radiogroup" aria-label="자기 평가">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} className={value && n <= value ? "on" : ""} disabled={disabled} onClick={() => onChange(n)} aria-label={`${n}점`}>
          ★
        </button>
      ))}
    </span>
  );
}
