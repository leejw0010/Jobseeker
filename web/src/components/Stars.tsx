export default function Stars({ value, onChange }: { value: number | null; onChange: (v: number) => void }) {
  return (
    <span className="stars" role="radiogroup" aria-label="자기 평가">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} className={value && n <= value ? "on" : ""} onClick={() => onChange(n)} aria-label={`${n}점`}>
          ★
        </button>
      ))}
    </span>
  );
}
