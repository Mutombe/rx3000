/** What gets asked about by itself, and what is waiting to be asked.
 *
 *  THE PREVIEW IS THE POINT
 *
 *  "Automatic" is a word that makes people assume the worst, and a buyer who
 *  does not know what a setting will do leaves it alone. So the list of lines
 *  that would go on tomorrow's request is shown beside the choice, before
 *  anybody commits to it, and the same list is what the button raises now.
 *
 *  AND IT SAYS WHAT IT WILL NOT DO
 *
 *  Nothing is ever emailed to a wholesaler by a machine. Said here in as many
 *  words rather than left to be discovered, because a buyer who suspects the
 *  software might be writing to their suppliers unsupervised will turn this
 *  off and go back to the telephone, which is the outcome it exists to
 *  prevent.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, errorText } from "../api";
import BusyButton from "../components/BusyButton";
import { useToast } from "../components/Toast";

interface Waiting {
  product_id: number;
  product: string;
  on_hand: number;
  reorder_level: number;
  wanted: number;
}

interface Auto {
  trigger: string;
  choices: string[];
  waiting: Waiting[];
  most_lines: number;
  note: string;
}

/** What each choice means, in the words a buyer would use. The server holds
 *  the same three and refuses anything else. */
const SAYS: Record<string, { label: string; why: string }> = {
  off: {
    label: "Nothing, I will ask by hand",
    why: "No request is raised for you. Choose this if the buying is done on "
       + "the telephone and a draft nobody sends would only be clutter.",
  },
  out_of_stock: {
    label: "Anything that has run out",
    why: "The lines that are already costing sales, which is where a second "
       + "price is worth waiting a day for.",
  },
  reorder: {
    label: "Anything at or below its reorder level",
    why: "A wider net, for a pharmacy that plans further ahead. It makes for "
       + "a longer request, and a request nobody reads is one no wholesaler "
       + "prices properly.",
  },
};

export default function RfqAuto({ onClose, onRaised }: {
  onClose: () => void;
  onRaised: () => void;
}) {
  const toast = useToast();
  const go = useNavigate();
  const [auto, setAuto] = useState<Auto | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.get<Auto>("/api/rfqs/auto")
      .then(setAuto)
      .catch((e) => setError(errorText(
        e, "What gets asked about automatically could not be read.")));
  }, []);
  useEffect(load, [load]);

  async function choose(trigger: string) {
    // Optimistic: the choice lands on the screen at once and the preview
    // catches up, because a radio button that waits on a round trip before
    // it moves reads as one that did not register the click.
    setAuto((a) => (a ? { ...a, trigger } : a));
    try {
      const said = await api.post<{ message: string }>("/api/rfqs/auto", { trigger });
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be saved."));
      load();
    }
  }

  async function raiseNow() {
    try {
      const said = await api.post<{ raised: boolean; id?: number; message: string }>(
        "/api/rfqs/auto/run");
      if (!said.raised) {
        toast.ok(said.message);
        return;
      }
      toast.ok(said.message);
      onRaised();
      if (said.id) go(`/rfqs/${said.id}`);
    } catch (e) {
      toast.error(errorText(e, "Nothing could be raised."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal rfq-auto" onClick={(e) => e.stopPropagation()}>
        <h2>Asking around by itself</h2>

        {error && <div className="alert danger">{error}</div>}

        {auto && (
          <>
            <p className="muted">{auto.note}</p>

            <div className="rfq-auto-choices">
              {auto.choices.map((c) => (
                <label key={c}
                       className={`rfq-auto-choice${auto.trigger === c ? " on" : ""}`}>
                  <input type="radio" name="rfq-auto" checked={auto.trigger === c}
                         onChange={() => void choose(c)} />
                  <span>
                    <b>{SAYS[c]?.label ?? c}</b>
                    <span className="muted small">{SAYS[c]?.why}</span>
                  </span>
                </label>
              ))}
            </div>

            {auto.trigger !== "off" && (
              <>
                <label className="field-label">
                  What would go on the next request
                </label>
                {auto.waiting.length === 0 ? (
                  <p className="muted small">
                    Nothing is waiting. Everything that has run out is either
                    already on order or already out for quotation.
                  </p>
                ) : (
                  <>
                    <div className="table-wrap rfq-auto-list">
                      <table className="dt">
                        <thead>
                          <tr>
                            <th>Medicine</th>
                            <th className="num">On hand</th>
                            <th className="num">Reorder at</th>
                            <th className="num">Would ask for</th>
                          </tr>
                        </thead>
                        <tbody>
                          {auto.waiting.map((w) => (
                            <tr key={w.product_id}>
                              <td>{w.product}</td>
                              <td className="num">{w.on_hand}</td>
                              <td className="num">{w.reorder_level}</td>
                              <td className="num">{w.wanted}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {auto.waiting.length >= auto.most_lines && (
                      <p className="hint">
                        Only the {auto.most_lines} emptiest go on one request.
                        The rest follow tomorrow, worst first.
                      </p>
                    )}
                  </>
                )}
              </>
            )}
          </>
        )}

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Close</button>
          {auto && auto.trigger !== "off" && (
            <BusyButton className="btn primary" onClick={raiseNow}
                        disabled={auto.waiting.length === 0}
                        busyLabel="Raising…">
              Raise it now instead of waiting
            </BusyButton>
          )}
        </div>
      </div>
    </div>
  );
}
