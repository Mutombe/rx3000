/** Light, dark, or whatever the device says.
 *
 *  Three states rather than two, because "dark" and "follow my device" are
 *  different answers. A two-way toggle has to guess which one an operator meant,
 *  and it guesses wrong every evening for anyone whose laptop switches at sunset.
 *
 *  The default is **System**, and nothing is written to storage until a choice is
 *  actually made. A fresh till therefore matches the machine it is running on —
 *  a dispensary that is dark at 6am is dark in here too, and only a deliberate
 *  choice overrides it.
 *
 *  What is applied is a `data-theme` attribute on `<html>`, and the stylesheet
 *  reads it in two places: `:root[data-theme="dark"]` for an explicit choice, and
 *  `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])` for the
 *  device. Under System the attribute is removed entirely, so the media query is
 *  the only thing deciding, which is what keeps a sunset switch instant with no
 *  listener involved.
 *
 *  The listener below exists only to tell React that the *resolved* theme moved,
 *  for the parts that read a colour in JavaScript rather than CSS: the charts.
 */
import { readStored, writeStored } from "./storage";

export type ThemeChoice = "light" | "dark" | "system";
/** What is actually on screen. System has resolved to one of these. */
export type Resolved = "light" | "dark";

const KEY = "theme";
const DARK = "(prefers-color-scheme: dark)";
const listeners = new Set<() => void>();

function isChoice(v: string | null): v is ThemeChoice {
  return v === "light" || v === "dark" || v === "system";
}

export function getChoice(): ThemeChoice {
  const stored = readStored(KEY);
  return isChoice(stored) ? stored : "system";
}

export function deviceIsDark(): boolean {
  return typeof window !== "undefined"
    && !!window.matchMedia
    && window.matchMedia(DARK).matches;
}

export function resolved(): Resolved {
  const choice = getChoice();
  if (choice !== "system") return choice;
  return deviceIsDark() ? "dark" : "light";
}

/** Put the *resolved* theme on `<html>`, always as a concrete value.
 *
 *  Under System this resolves the device preference here rather than leaving the
 *  attribute off and letting a `prefers-color-scheme` block decide. That is a
 *  deliberate trade: it costs a `matchMedia` read and a listener, and it saves
 *  maintaining two copies of every dark token, one under the media query and one
 *  under the attribute. The duplicated version drifted within a day.
 *
 *  The choice itself is kept in a second attribute, so CSS or a test can see the
 *  difference between "dark" and "system, and the device says dark". */
function paint(choice: ThemeChoice) {
  const root = document.documentElement;
  root.setAttribute("data-theme", choice === "system"
    ? (deviceIsDark() ? "dark" : "light")
    : choice);
  root.setAttribute("data-theme-choice", choice);
}

export function setChoice(choice: ThemeChoice) {
  // System is the default, so it is stored as *nothing*. Otherwise a till that
  // was set to System would keep the word "system" forever, and the day the
  // default changes it would not follow.
  writeStored(KEY, choice === "system" ? null : choice);
  paint(choice);
  for (const l of listeners) l();
}

/** Called once at startup, after the inline script in index.html has already
 *  painted. This re-applies the same value — cheap, and it keeps the attribute
 *  correct if the inline script was ever stripped or failed. */
export function startTheme() {
  paint(getChoice());
  if (window.matchMedia) {
    window.matchMedia(DARK).addEventListener("change", () => {
      // Only under System. With an explicit choice the device moving changes
      // nothing, and repainting would fight the operator's decision.
      if (getChoice() !== "system") return;
      paint("system");
      for (const l of listeners) l();
    });
  }
}

export function subscribeTheme(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
