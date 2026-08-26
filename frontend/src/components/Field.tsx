/** Field wrapper.
 *
 *  Owns the label, hint, error slot and — critically — the width. Pages set a
 *  `span` on the 12-column form grid instead of reaching for an inline style,
 *  which is what let control sizing drift in the first place.
 */
import { ReactNode, useId } from "react";
import Checkbox from "./Checkbox";

export type Span = 2 | 3 | 4 | 6 | 8 | 12;

export default function Field({
  label, hint, error, span = 6, required, children, htmlFor,
}: {
  label?: string;
  hint?: ReactNode;
  error?: string;
  span?: Span;
  required?: boolean;
  children: ReactNode;
  htmlFor?: string;
}) {
  const auto = useId();
  const id = htmlFor ?? auto;
  return (
    <div className={`field span-${span}${error ? " invalid" : ""}`}>
      {label && (
        <label htmlFor={id}>
          {label}
          {required && <span className="req" aria-hidden> *</span>}
        </label>
      )}
      {children}
      {error ? <div className="err">{error}</div> : hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

/** A row of fields on the 12-column grid. */
export function FormRow({ children }: { children: ReactNode }) {
  return <div className="form-row">{children}</div>;
}

/** Checkbox with its label on one line, aligned to the control baseline. */
export function CheckRow({ checked, onChange, children, disabled }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  // Renders the design system's checkbox rather than a second, native one.
  // This component is the shared row, so every page using it was drawing an
  // operating-system tick box no matter what the rest of the form looked like.
  return (
    <div className="check-row">
      <Checkbox id={id} checked={checked} disabled={disabled} onChange={onChange}>
        {children}
      </Checkbox>
    </div>
  );
}
