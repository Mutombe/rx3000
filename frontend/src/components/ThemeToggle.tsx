/** The theme control in the top bar.
 *
 *  A segmented control rather than a menu. Three reasons, all about a counter:
 *
 *    - **It shows the current state without being opened.** A pharmacist glancing
 *      up can see the screen is on System, which is the answer to "why did it go
 *      dark on me".
 *    - **Any state is one click away.** A menu makes every change two.
 *    - **It cannot be half-open.** Nothing to dismiss while a customer waits.
 *
 *  Rendered as a radiogroup, so arrow keys move through it the way the control
 *  looks like it should.
 */
import { Desktop, Moon, Sun } from "@phosphor-icons/react";
import { useTheme } from "../hooks/useTheme";
import type { ThemeChoice } from "../theme";
import { deviceIsDark } from "../theme";

const OPTIONS: { id: ThemeChoice; label: string; Icon: typeof Sun }[] = [
  { id: "light", label: "Light", Icon: Sun },
  { id: "dark", label: "Dark", Icon: Moon },
  { id: "system", label: "System", Icon: Desktop },
];

export default function ThemeToggle() {
  const { choice, set } = useTheme();

  return (
    <div className="theme-seg" role="radiogroup" aria-label="Appearance">
      {OPTIONS.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={id === choice}
          className={`theme-opt${id === choice ? " is-on" : ""}`}
          onClick={() => set(id)}
          // Said out loud on the System option, because "follows your device" is
          // only useful if you also know what the device currently says.
          data-tip={id === "system"
            ? `Follow this device, which is set to ${deviceIsDark() ? "dark" : "light"}`
            : label}
        >
          <Icon size={13} weight={id === choice ? "fill" : "regular"} />
          {/* The word stays visible. Three unlabelled glyphs in a top bar make
              somebody click one to find out what it does, and a sun and a screen
              at 15px are not obviously different things. */}
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}
