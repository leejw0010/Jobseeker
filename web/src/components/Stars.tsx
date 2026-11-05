import { useEffect, useRef } from 'react';

/** 자기 평가 별점: 선택 상태와 방향키 이동을 제공한다. */
export default function Stars({ value, onChange, disabled = false }: { value: number | null; onChange: (v: number) => void; disabled?: boolean }) {
  const group = useRef<HTMLSpanElement>(null);
  const focusAfterSave = useRef<number | null>(null);
  useEffect(() => {
    if (!disabled && focusAfterSave.current === value) {
      group.current?.querySelector<HTMLButtonElement>(`[aria-label="${value}점"]`)?.focus();
      focusAfterSave.current = null;
    }
  }, [disabled, value]);
  return (
    <span ref={group} className="stars" role="radiogroup" aria-label="자기 평가">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} role="radio" aria-checked={value === n} tabIndex={n === (value ?? 1) ? 0 : -1}
          className={value && n <= value ? "on" : ""} disabled={disabled} onClick={() => onChange(n)} aria-label={`${n}점`}
          onKeyDown={event => {
            const next = event.key === 'Home' ? 1 : event.key === 'End' ? 5
              : ['ArrowRight','ArrowDown'].includes(event.key) ? n % 5 + 1
              : ['ArrowLeft','ArrowUp'].includes(event.key) ? (n + 3) % 5 + 1 : null;
            if(next === null) return;
            event.preventDefault();
            focusAfterSave.current = next;
            onChange(next);
          }}>
          ★
        </button>
      ))}
    </span>
  );
}
