import { useEffect, useState } from "react";
import { getChoice, resolved, setChoice, subscribeTheme } from "../theme";
import type { Resolved, ThemeChoice } from "../theme";

/** The theme, for components that need to react to it rather than just be
 *  styled by it — the charts, which pick series colours in JavaScript. */
export function useTheme(): { choice: ThemeChoice; mode: Resolved; set: (c: ThemeChoice) => void } {
  const [, force] = useState(0);
  useEffect(() => subscribeTheme(() => force((n) => n + 1)), []);
  return { choice: getChoice(), mode: resolved(), set: setChoice };
}
