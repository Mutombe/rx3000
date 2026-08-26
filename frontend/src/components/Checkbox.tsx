/** A checkbox that belongs to this design system.
 *
 *  A native checkbox is drawn by the operating system: it ignores the palette,
 *  changes size between Windows and macOS, and cannot show a hint under its
 *  label. Every one of them in this application was also wrapped in the same
 *  hand-written `<label style={{display:"flex", alignItems:"center", gap:8}}>`,
 *  copied twenty-four times with three different gap values — which is what a
 *  missing component looks like from the outside.
 *
 *  The real input is still there and still focusable; it is the box that is
 *  drawn, not the behaviour. Keyboard, screen readers and form semantics are
 *  the browser's, because reimplementing those is how a control becomes
 *  beautiful and unusable.
 */
import React, { ReactNode } from "react";

export default function Checkbox({
  checked, onChange, children, hint, disabled, id, onClick, className = "",
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** The label. Clicking it toggles, because a 14px target does not. */
  children?: ReactNode;
  /** A quieter second line — what this actually does, when that is not obvious. */
  hint?: ReactNode;
  disabled?: boolean;
  id?: string;
  /** For a checkbox inside a row that is itself clickable: the tick must not
   *  also trigger the row. */
  onClick?: (e: React.MouseEvent) => void;
  className?: string;
}) {
  return (
    <label className={`cbx${disabled ? " is-disabled" : ""}${className ? " " + className : ""}`} onClick={onClick}>
      <input
        id={id}
        type="checkbox"
        className="cbx-input"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="cbx-box" aria-hidden="true">
        <svg viewBox="0 0 12 12" className="cbx-tick">
          <path d="M2.5 6.2l2.3 2.3 4.7-4.9" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      {(children || hint) && (
        <span className="cbx-text">
          {children}
          {hint && <span className="cbx-hint">{hint}</span>}
        </span>
      )}
    </label>
  );
}
