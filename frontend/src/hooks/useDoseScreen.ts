/** The dose check, without a panel to put it in.
 *
 *  The check itself was never the problem. It reads the directions typed
 *  against each line, works out the daily dose, and says when one is over a
 *  maximum or when the directions could not be read at all — the second being
 *  the common and useful case, because a line whose directions nobody can parse
 *  is a line nobody has checked.
 *
 *  What was wrong was where it lived: a panel under the table, permanently on
 *  screen, taking more room than the script it was about. So the check moved
 *  out of the panel and into a hook, and the finding is shown where it belongs
 *  — on the row of the medicine it is about, as a triangle that costs nothing
 *  until there is something to say.
 *
 *  MATCHING THE ANSWER BACK TO A ROW
 *
 *  The screen answers with the product's NAME, not its id: the endpoint builds
 *  `f"{product.name} {product.strength}".strip()` server-side and `doses.py`
 *  echoes that into every finding.
 *
 *  So the caller reconstructs the same string and the match is exact — no
 *  prefix, no fuzz. A safety marker that appears on the wrong row is worse than
 *  one that does not appear at all, and a prefix match on medicine names would
 *  eventually put one on the wrong row: this catalogue has AMOXYCILLIN 250MG
 *  and AMOXYCILLIN 250MG/5ML SUSP, which share their first twenty characters.
 *
 *  THE SAME REQUEST, THE SAME DEBOUNCE, THE SAME GUARD
 *
 *  Lifted from `InteractionPanel` rather than rewritten, including the two
 *  things that are easy to leave out and expensive to leave out: it is
 *  debounced, so adding four items in four seconds is one request; and it is
 *  guarded, so the answer to a two-item basket cannot land after the answer to
 *  a four-item one and quietly replace it. Without that the screen shows a
 *  clean result for a basket that is no longer on the counter, which is the
 *  worst way for a safety check to be wrong.
 */
import { useEffect, useState } from "react";
import { api } from "../api";
import type { DoseFinding, Screen } from "../components/InteractionPanel";

export interface DoseLine {
  product_id: number;
  /** `"{name} {strength}"`, exactly as the server builds it — the string the
   *  finding will come back under. Not sent; used to match the answer to a row. */
  name: string;
  instructions: string;
  quantity?: number;
}

export interface DoseScreenResult {
  /** Findings by product id, so a row can ask about itself. */
  byProduct: Map<number, DoseFinding>;
  /** How many are over a maximum. The page gates the dispense on this. */
  major: number;
  busy: boolean;
}

export function useDoseScreen(
  patientId: number | null,
  lines: DoseLine[],
): DoseScreenResult {
  const [screen, setScreen] = useState<Screen | null>(null);
  const [busy, setBusy] = useState(false);

  const productIds = lines.map((l) => l.product_id);
  /* Keyed on the directions as well as the products: changing "1 t od" to
     "3 tabs qds" is a different question, and a check that only watched the
     product list would keep showing the answer to the old one. */
  const key = `${patientId ?? 0}:${[...productIds].sort((a, b) => a - b).join(",")}`
    + `:${lines.map((l) => `${l.product_id}=${l.instructions}`).sort().join("|")}`;

  useEffect(() => {
    if (!lines.length) {
      setScreen(null);
      return;
    }
    let live = true;
    const t = window.setTimeout(() => {
      setBusy(true);
      api.post<Screen>("/api/dispensing/interaction-screen", {
        patient_id: patientId,
        product_ids: productIds,
        // `name` is not sent: the server builds the label from the product it
        // looks up, and a name from here would be a second source for the same
        // string. It is on `DoseLine` only so the answer can be matched back.
        lines: lines.map((l) => ({
          product_id: l.product_id,
          instructions: l.instructions,
          quantity: l.quantity,
        })),
      })
        .then((r) => { if (live) setScreen(r); })
        .catch(() => { if (live) setScreen(null); })
        .finally(() => { if (live) setBusy(false); });
    }, 350);
    return () => { live = false; window.clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const byProduct = new Map<number, DoseFinding>();
  for (const f of screen?.doses?.found ?? []) {
    // "unknown" is the checker saying it holds nothing for this medicine, or
    // that the patient is a child and it will not judge. Neither is a finding
    // ABOUT the medicine, and a triangle meaning "we have nothing to say" is a
    // triangle nobody reads twice.
    if (f.severity === "unknown") continue;
    const line = lines.find((l) => l.name === f.product);
    if (line) byProduct.set(line.product_id, f);
  }

  return { byProduct, major: screen?.doses?.major ?? 0, busy };
}
