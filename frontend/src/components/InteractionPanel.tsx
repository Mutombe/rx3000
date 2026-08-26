/** Interaction screening, run as the basket changes rather than on a button.
 *
 *  The version this replaces was a button labelled "AI interaction check". Two
 *  things were wrong with that. It only ran when somebody remembered to press
 *  it, which on the busy afternoon it was written for is never; and the local
 *  checker — twelve established pairs, matched against the patient's own
 *  dispensing history — was not wired to the screen at all. The endpoint
 *  existed and nothing called it.
 *
 *  **What it never does is say a combination is safe.** The checker holds twelve
 *  pairs. A clear result means none of those twelve were found, which is a
 *  different and true sentence, and the coverage note is on screen whether
 *  anything was flagged or not. A pharmacist who is told twice that the system
 *  checks interactions will trust it the third time, and the pair it does not
 *  hold is the one that goes out.
 *
 *  A major finding asks for an acknowledgement before the dispense button
 *  enables. It does not hard-block: blocking on twelve pairs while missing
 *  thousands teaches exactly the over-trust this module exists to prevent.
 */
import { useEffect, useState } from "react";
import { ShieldWarning, Warning } from "@phosphor-icons/react";
import { api } from "../api";

export interface Finding {
  severity: "major" | "moderate" | "minor";
  between: [string, string];
  context: string;
  with_history: boolean;
  effect: string;
  action: string;
}

export interface Screen {
  checked: number;
  history_checked: number;
  pairs_consulted: number;
  found: Finding[];
  major: number;
  summary: string;
  coverage: string;
  history_source: string;
}

export default function InteractionPanel({
  patientId, productIds, acknowledged, onAcknowledge, onScreened,
}: {
  patientId: number | null;
  productIds: number[];
  /** Whether the pharmacist has accepted the major findings. */
  acknowledged: boolean;
  onAcknowledge: (value: boolean) => void;
  /** Tells the page how many major findings are outstanding. */
  onScreened: (major: number) => void;
}) {
  const [screen, setScreen] = useState<Screen | null>(null);
  const [busy, setBusy] = useState(false);
  const key = `${patientId ?? 0}:${[...productIds].sort((a, b) => a - b).join(",")}`;

  useEffect(() => {
    if (!productIds.length) {
      setScreen(null);
      onScreened(0);
      return;
    }
    /* Debounced, and the reply is dropped if the basket moved on.
       Adding four items in four seconds fires four requests, and without the
       guard the answer to a two-item basket can land after the answer to a
       four-item one and quietly replace it — a screen showing a clean result
       for a basket that is no longer on the counter. */
    let live = true;
    const t = window.setTimeout(() => {
      setBusy(true);
      api.post<Screen>("/api/dispensing/interaction-screen", {
        patient_id: patientId, product_ids: productIds,
      })
        .then((r) => { if (live) { setScreen(r); onScreened(r.major); } })
        .catch(() => { if (live) { setScreen(null); onScreened(0); } })
        .finally(() => { if (live) setBusy(false); });
    }, 350);
    return () => { live = false; window.clearTimeout(t); };
    // Keyed on the basket contents, not the array identity: a re-render that
    // rebuilds the same list of ids must not re-run the check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!productIds.length) return null;

  const major = screen?.found.filter((f) => f.severity === "major") ?? [];
  const rest = screen?.found.filter((f) => f.severity !== "major") ?? [];

  return (
    <div className={`ix${major.length ? " ix-major" : ""}`}>
      <div className="ix-head">
        <ShieldWarning size={15} weight={major.length ? "fill" : "regular"} />
        <b>
          {busy ? "Screening…"
            : major.length ? `${major.length} major interaction${major.length === 1 ? "" : "s"}`
            : screen?.summary ?? ""}
        </b>
        {screen && (
          <span className="muted">
            {screen.checked} on this script · {screen.history_source.toLowerCase()}
          </span>
        )}
      </div>

      {[...major, ...rest].map((f, i) => (
        <div key={i} className={`ix-row is-${f.severity}`}>
          <Warning size={14} weight="fill" />
          <div>
            <b>{f.between[0]} + {f.between[1]}</b>
            {/* Which side is which. "Both on this script" and "against a repeat
                they are already on" are different conversations to have with the
                patient, and the pharmacist should not have to work it out. */}
            <span className="ix-context">{f.context}</span>
            <p>{f.effect}</p>
            <p className="ix-action">{f.action}</p>
          </div>
        </div>
      ))}

      {major.length > 0 && (
        <label className="ix-ack">
          <input type="checkbox" checked={acknowledged}
                 onChange={(e) => onAcknowledge(e.target.checked)} />
          I have read {major.length === 1 ? "this finding" : "these findings"} and
          checked {major.length === 1 ? "it" : "them"} with the prescriber or the patient.
        </label>
      )}

      {/* On screen whether or not anything was flagged. The limits of a checker
          are only useful at the moment somebody is relying on it. */}
      {screen && <p className="ix-coverage">{screen.coverage}</p>}
    </div>
  );
}
