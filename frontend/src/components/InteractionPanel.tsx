/** Safety screening, run as the basket changes rather than on a button.
 *
 *  Two checks in one panel, because they are one question — is this safe to hand
 *  over — and a pharmacist should not have to look in two places for the answer:
 *
 *    - **Interactions**, against the other lines on the script *and* against what
 *      this patient has actually been dispensed in the last six months.
 *    - **Dose ranges**, read out of the directions typed on each line: quantity
 *      per dose times doses per day, against the maximum held for that
 *      ingredient.
 *
 *  The version this replaces was a button marked "AI interaction check". It only
 *  ran when somebody remembered to press it, which on the busy afternoon it was
 *  written for is never; the local interaction checker was not wired to the
 *  screen at all; and there was no dose checking anywhere in the product.
 *
 *  **What it never does is say something is safe.** Twelve interaction pairs and
 *  forty dose limits. A clear result means none of those were exceeded, which is
 *  a different and true sentence, and both coverage notes are on screen whether
 *  anything was flagged or not. A pharmacist told twice that the system checks
 *  doses will trust it the third time, and the drug it does not hold is the one
 *  that goes out at four times the maximum. A line nothing is known about is
 *  named rather than passing silently.
 *
 *  A major finding of either kind asks for an acknowledgement before the dispense
 *  button enables. It does not hard-block: refusing outright on a table this
 *  small teaches exactly the over-trust both modules are written against.
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

export interface DoseFinding {
  severity: "major" | "unknown" | "unread";
  product: string;
  detail: string;
  action: string;
}

export interface DoseScreen {
  checked: number;
  limits_consulted: number;
  found: DoseFinding[];
  major: number;
  summary: string;
  not_covered: string[];
  coverage: string;
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
  doses: DoseScreen;
  patient_age: number | null;
}

export default function InteractionPanel({
  patientId, productIds, lines, acknowledged, onAcknowledge, onScreened,
}: {
  patientId: number | null;
  productIds: number[];
  /** The directions typed against each line. The dose checker needs to know how
   *  often, and only this screen knows that. */
  lines?: { product_id: number; instructions: string; quantity?: number }[];
  /** Whether the pharmacist has accepted the major findings. */
  acknowledged: boolean;
  onAcknowledge: (value: boolean) => void;
  /** Tells the page how many major findings are outstanding. */
  onScreened: (major: number) => void;
}) {
  const [screen, setScreen] = useState<Screen | null>(null);
  const [busy, setBusy] = useState(false);
  /* Keyed on the directions as well as the products: changing "1 t od" to
     "3 tabs qds" is a different question, and a check that only watched the
     product list would keep showing the answer to the old one. */
  const key = `${patientId ?? 0}:${[...productIds].sort((a, b) => a - b).join(",")}`
    + `:${(lines ?? []).map((l) => `${l.product_id}=${l.instructions}`).sort().join("|")}`;

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
        patient_id: patientId, product_ids: productIds, lines: lines ?? [],
      })
        // Either check can hold the dispense: an interaction and an overdose are
        // both reasons to stop and ask, and the button should not care which.
        .then((r) => { if (live) { setScreen(r); onScreened(r.major + (r.doses?.major ?? 0)); } })
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
  const doses = screen?.doses;
  const doseMajor = doses?.major ?? 0;
  const toAcknowledge = major.length + doseMajor;

  return (
    <div className={`ix${toAcknowledge ? " ix-major" : ""}`}>
      <div className="ix-head">
        <ShieldWarning size={15} weight={major.length ? "fill" : "regular"} />
        <b>
          {busy ? "Screening…"
            : toAcknowledge
              ? [major.length && `${major.length} major interaction${major.length === 1 ? "" : "s"}`,
                 doseMajor && `${doseMajor} dose${doseMajor === 1 ? "" : "s"} over the maximum`]
                  .filter(Boolean).join(" · ")
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

      {/* Dose findings, under the interactions. A dose that is over the maximum
          is the same kind of stop-and-ask as an interaction, so it reads the
          same way rather than living in a second panel somewhere else. */}
      {doses?.found.map((f, i) => (
        <div key={`d${i}`} className={`ix-row is-${f.severity === "major" ? "major" : "minor"}`}>
          <Warning size={14} weight="fill" />
          <div>
            <b>{f.product}</b>
            <span className="ix-context">
              {f.severity === "major" ? "over the maximum held here"
                : f.severity === "unknown" ? "not judged"
                : "directions could not be read"}
            </span>
            <p>{f.detail}</p>
            <p className="ix-action">{f.action}</p>
          </div>
        </div>
      ))}

      {/* Said out loud rather than passing silently. A line nothing was known
          about is the one a pharmacist most needs to know went unchecked. */}
      {doses && doses.not_covered.length > 0 && (
        <p className="ix-coverage">
          No dose limit is held here for {doses.not_covered.join(", ")}, so
          {doses.not_covered.length === 1 ? " it was" : " they were"} not checked.
        </p>
      )}

      {toAcknowledge > 0 && (
        <label className="ix-ack">
          <input type="checkbox" checked={acknowledged}
                 onChange={(e) => onAcknowledge(e.target.checked)} />
          I have read {toAcknowledge === 1 ? "this finding" : "these findings"} and
          checked {toAcknowledge === 1 ? "it" : "them"} with the prescriber or the patient.
        </label>
      )}

      {/* On screen whether or not anything was flagged. The limits of a checker
          are only useful at the moment somebody is relying on it. */}
      {screen && <p className="ix-coverage">{screen.coverage}</p>}
      {doses && <p className="ix-coverage">{doses.coverage}</p>}
    </div>
  );
}
