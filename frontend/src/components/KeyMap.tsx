/** Key map overlay.
 *
 *  Generated from the same bindings that are actually registered, so a shortcut
 *  cannot exist without appearing here — and cannot appear here without working.
 */
import { Hotkey, useKeyMap } from "../hooks/useHotkeys";

export function KeyCap({ combo }: { combo: string }) {
  return (
    <span className="keycap">
      {combo.split("+").map((part, i) => (
        <span key={i}>{i > 0 && <em>+</em>}{part}</span>
      ))}
    </span>
  );
}

/** The always-visible strip of primary actions along the bottom of a workflow. */
export function KeyBar({ keys }: { keys: Hotkey[] }) {
  return (
    <div className="keybar">
      {keys.filter((k) => /^F\d{1,2}$/i.test(k.combo)).map((k) => (
        <button
          key={k.combo}
          className="keybar-item"
          onClick={k.run}
          disabled={k.disabled}
          title={k.label}
        >
          <KeyCap combo={k.combo} />
          <span className="keybar-label">{k.label}</span>
        </button>
      ))}
    </div>
  );
}

export default function KeyMap({ keys, open, onClose }: {
  keys: Hotkey[];
  open: boolean;
  onClose: () => void;
}) {
  const groups = useKeyMap(keys);
  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal keymap" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 620 }}>
        <h2>Keyboard shortcuts</h2>
        <p className="muted">
          Function keys work while you are typing, so your hands never leave the keyboard.
        </p>
        {groups.map((g) => (
          <div key={g.name} className="keymap-group">
            <h4>{g.name}</h4>
            {g.items.map((k) => (
              <div key={k.combo} className={`keymap-row${k.disabled ? " disabled" : ""}`}>
                <KeyCap combo={k.combo} />
                <span>{k.label}</span>
              </div>
            ))}
          </div>
        ))}
        <div className="modal-actions">
          <button className="secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
