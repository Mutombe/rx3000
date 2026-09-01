/** Dose screening, run as the basket changes rather than on a button.
 *
 *  Reads the directions typed on each line — quantity per dose times doses per
 *  day — against the maximum held for that ingredient.
 *
 *  WHAT WAS TAKEN OUT, AND WHAT WAS NOT
 *
 *  This panel used to report interactions as well, from twelve pairs held
 *  locally. That half is gone: the AI interaction check on the same screen
 *  covers it, and two checkers answering one question meant a wall of text on
 *  every script saying that neither of them found anything.
 *
 *  The dose half stays, because it is not an interaction check and nothing else
 *  in the product does it. The finding that prompted this rewrite was exactly
 *  that kind: an adult maximum on an eight-year-old, which no interaction
 *  checker would ever raise.
 *
 *  WHY IT IS QUIET WHEN THERE IS NOTHING TO SAY
 *
 *  It used to render a full-width panel on every script — a heading saying
 *  nothing was found, a row saying a line was not judged, and two paragraphs of
 *  disclaimer — directly above the button somebody was trying to press. A
 *  warning surrounded by four sentences of nothing is a warning nobody reads.
 *
 *  So a clear result is one quiet line. **It still never says "safe".** Forty
 *  dose limits: a clear result means none of those was exceeded, which is a
 *  different and true sentence, and the coverage note is still there — one
 *  line rather than a paragraph, and always present, because the limits of a
 *  checker matter most at the moment somebody is relying on it. A line nothing
 *  is known about is named rather than passing silently.
 *
 *  A dose over the maximum asks for an acknowledgement before the dispense
 *  button enables. It does not hard-block: refusing outright on a table this
 *  small teaches exactly the over-trust the module is written against.
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
        // Only a dose over the maximum holds the dispense now. Interactions
        // are the AI check's job, and it is a deliberate press rather than a
        // gate.
        .then((r) => { if (live) { setScreen(r); onScreened(r.doses?.major ?? 0); } })
        .catch(() => { if (live) { setScreen(null); onScreened(0); } })
        .finally(() => { if (live) setBusy(false); });
    }, 350);
    return () => { live = false; window.clearTimeout(t); };
    // Keyed on the basket contents, not the array identity: a re-render that
    // rebuilds the same list of ids must not re-run the check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!productIds.length) return null;

  const doses = screen?.doses;
  const doseMajor = doses?.major ?? 0;
  const toAcknowledge = doseMajor;
  // A finding worth the space: over the maximum, or directions that could not
  // be read. "Not judged" is not a finding — it is the checker saying it has
  // nothing to offer on that line, which belongs in the coverage line below
  // with everything else it does not cover.
  const findings = (doses?.found ?? []).filter((f) => f.severity !== "unknown");
  const notJudged = (doses?.found ?? [])
    .filter((f) => f.severity === "unknown").map((f) => f.product);
  const unchecked = [...notJudged, ...(doses?.not_covered ?? [])];

  // Nothing to report: one line, not a panel. It still refuses to say "safe".
  if (!busy && findings.length === 0) {
    return (
      <p className="ix-clear" title={doses?.coverage ?? ""}>
        <ShieldWarning size={13} />
        <span>
          No dose here exceeds a maximum this system holds.
          {unchecked.length > 0 && (
            <> Nothing is held for <b>{unchecked.join(", ")}</b>, so
              {unchecked.length === 1 ? " it was" : " they were"} not checked.</>
          )}
        </span>
      </p>
    );
  }

  return (
    <div className={`ix${toAcknowledge ? " ix-major" : ""}`}>
      <div className="ix-head">
        <ShieldWarning size={15} weight={doseMajor ? "fill" : "regular"} />
        <b>
          {busy ? "Checking doses…"
            : doseMajor
              ? `${doseMajor} dose${doseMajor === 1 ? "" : "s"} over the maximum`
              : `${findings.length} dose${findings.length === 1 ? "" : "s"} to look at`}
        </b>
      </div>

      {findings.map((f, i) => (
        <div key={`d${i}`} className={`ix-row is-${f.severity === "major" ? "major" : "minor"}`}>
          <Warning size={14} weight="fill" />
          <div>
            <b>{f.product}</b>
            <span className="ix-context">
              {f.severity === "major" ? "over the maximum held here"
                : "directions could not be read"}
            </span>
            <p>{f.detail}</p>
            <p className="ix-action">{f.action}</p>
          </div>
        </div>
      ))}

      {/* Said out loud rather than passing silently. A line nothing was known
          about is the one a pharmacist most needs to know went unchecked. */}
      {unchecked.length > 0 && (
        <p className="ix-coverage">
          Nothing is held here for {unchecked.join(", ")}, so
          {unchecked.length === 1 ? " it was" : " they were"} not checked.
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

      {/* The limits of a checker are only useful at the moment somebody is
          relying on it, so this is present whenever a finding is. */}
      {doses && <p className="ix-coverage">{doses.coverage}</p>}
    </div>
  );
}
