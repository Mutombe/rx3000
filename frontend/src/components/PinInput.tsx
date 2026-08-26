/** Four boxes for a till PIN.
 *
 *  One box per digit rather than a password field, because this prompt appears
 *  mid-transaction with a patient waiting: the reader can see how many digits
 *  are left without counting dots, and the caret never has to be placed.
 *
 *  Behaviour that matters at a counter:
 *    - typing moves forward, backspace moves back, and both work on the box you
 *      are actually in rather than on a hidden cursor position;
 *    - a paste of four digits fills all four, because people paste;
 *    - it submits itself on the last digit, so the common case is four
 *      keystrokes and nothing else;
 *    - digits are masked. A PIN typed at a counter is a PIN read over a
 *      shoulder, and the boxes are large enough to read from a metre away.
 */
import { useEffect, useRef, useState } from "react";

export default function PinInput({
  length = 4, value, onChange, onComplete, disabled, autoFocus = true, invalid,
}: {
  length?: number;
  value: string;
  onChange: (next: string) => void;
  /** Called once the last digit lands, so the caller need not watch the value. */
  onComplete?: (pin: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  invalid?: boolean;
}) {
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const [shake, setShake] = useState(false);

  useEffect(() => { if (autoFocus) boxes.current[0]?.focus(); }, [autoFocus]);

  // A refusal is felt as well as read: the boxes move, then clear themselves so
  // the next attempt starts from an empty row rather than a wrong one.
  useEffect(() => {
    if (!invalid) return;
    setShake(true);
    const t = window.setTimeout(() => { setShake(false); boxes.current[0]?.focus(); }, 420);
    return () => window.clearTimeout(t);
  }, [invalid]);

  const put = (i: number, digit: string) => {
    const next = (value.padEnd(length, " ").slice(0, i) + digit +
                  value.padEnd(length, " ").slice(i + 1)).replace(/\s/g, "");
    onChange(next);
    if (digit && i < length - 1) boxes.current[i + 1]?.focus();
    if (next.length === length) onComplete?.(next);
  };

  return (
    <div className={`pin${shake ? " is-wrong" : ""}${invalid ? " is-invalid" : ""}`}>
      {Array.from({ length }, (_, i) => (
        <input
          key={i}
          ref={(el) => { boxes.current[i] = el; }}
          className="pin-box"
          inputMode="numeric"
          autoComplete="one-time-code"
          type="password"
          maxLength={1}
          disabled={disabled}
          aria-label={`Digit ${i + 1} of ${length}`}
          value={value[i] ?? ""}
          onChange={(e) => {
            const digit = e.target.value.replace(/\D/g, "").slice(-1);
            if (digit) put(i, digit);
          }}
          onKeyDown={(e) => {
            if (e.key === "Backspace") {
              e.preventDefault();
              if (value[i]) put(i, "");
              else if (i > 0) { boxes.current[i - 1]?.focus(); put(i - 1, ""); }
            }
            if (e.key === "ArrowLeft" && i > 0) boxes.current[i - 1]?.focus();
            if (e.key === "ArrowRight" && i < length - 1) boxes.current[i + 1]?.focus();
          }}
          onPaste={(e) => {
            const digits = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, length);
            if (!digits) return;
            e.preventDefault();
            onChange(digits);
            boxes.current[Math.min(digits.length, length - 1)]?.focus();
            if (digits.length === length) onComplete?.(digits);
          }}
        />
      ))}
    </div>
  );
}
