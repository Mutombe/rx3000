/** Keyboard shortcuts.
 *
 *  A dispensary runs hundreds of scripts a day and the pharmacist never reaches
 *  for the mouse. The incumbent system drives an entire script from function
 *  keys; matching that is not a nicety, it is the difference between being
 *  adopted and being rejected on the stopwatch.
 *
 *  Rules that keep shortcuts from becoming a hazard:
 *   - function keys work everywhere, including inside a text field, because
 *     that is where the pharmacist's hands already are;
 *   - plain-letter shortcuts never fire while typing;
 *   - a disabled action is skipped rather than silently doing nothing;
 *   - every binding carries a label, so the key map is generated from the same
 *     source of truth that binds the keys — a shortcut can never go undocumented.
 */
import { useEffect, useMemo } from "react";

export interface Hotkey {
  /** "F2", "Ctrl+R", "Escape", "?" */
  combo: string;
  label: string;
  run: () => void;
  disabled?: boolean;
  /** Group heading in the key map overlay. */
  group?: string;
}

function comboOf(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey) parts.push("Ctrl");
  if (e.altKey) parts.push("Alt");
  if (e.shiftKey && e.key.length > 1) parts.push("Shift");
  parts.push(e.key.length === 1 ? e.key.toUpperCase() : e.key);
  return parts.join("+");
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

export function useHotkeys(keys: Hotkey[], enabled = true) {
  // Rebind only when the set actually changes, not on every render.
  const signature = keys.map((k) => `${k.combo}:${k.disabled ? 0 : 1}`).join("|");

  useEffect(() => {
    if (!enabled) return;
    function onKey(e: KeyboardEvent) {
      const pressed = comboOf(e);
      const hit = keys.find((k) => k.combo.toUpperCase() === pressed.toUpperCase());
      if (!hit || hit.disabled) return;

      // Function keys and modifier combos are safe mid-typing; bare letters are not.
      const isFunctionKey = /^F\d{1,2}$/i.test(hit.combo);
      const hasModifier = /ctrl|alt/i.test(hit.combo);
      const isEscape = hit.combo.toLowerCase() === "escape";
      if (isTyping(e.target) && !isFunctionKey && !hasModifier && !isEscape) return;

      e.preventDefault();
      e.stopPropagation();
      hit.run();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, enabled, keys]);
}

/** Group the bindings for the key map overlay. */
export function useKeyMap(keys: Hotkey[]) {
  return useMemo(() => {
    const groups = new Map<string, Hotkey[]>();
    keys.forEach((k) => {
      const g = k.group ?? "Actions";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g)!.push(k);
    });
    return [...groups.entries()].map(([name, items]) => ({ name, items }));
  }, [keys]);
}
