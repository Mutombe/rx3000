/** Which printer each kind of document goes to, on this till.
 *
 *  Set once, here, and never asked again. That is the whole design: a dialog at
 *  the counter asking where the label should go is a question whose answer has
 *  not changed since the printer was plugged in, put to somebody with a patient
 *  in front of them.
 *
 *  ON THIS TILL, NOT IN THE DATABASE
 *
 *  "The roll by the counter" is a property of this machine. Two tills in the
 *  same pharmacy have different answers, and a pharmacy with a branch has four.
 *  Windows also names them locally — the same physical printer is called
 *  something different on each machine that shares it. So this lives in local
 *  storage beside the label roll that was already there, and nowhere near the
 *  pharmacy's data.
 *
 *  EVERYTHING FALLS BACK TO THE LABEL ROLL
 *
 *  A till that has only ever chosen one printer keeps printing everything on
 *  it. Nothing here has to be filled in for the upgrade to be invisible, which
 *  is why the fields say "same as the dispensing label" rather than sitting
 *  empty and looking unfinished.
 */
import { useEffect, useState } from "react";
import * as roll from "../shellPrinter";

export default function PrinterRoutes() {
  const [printers, setPrinters] = useState<string[]>([]);
  const [routes, setRoutes] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    roll.listPrinters()
      .then(setPrinters)
      .catch(() => setPrinters([]))
      .finally(() => setLoading(false));
    const current: Record<string, string> = {};
    for (const d of roll.DOC_KINDS) current[d.kind] = roll.explicitRoute(d.kind);
    setRoutes(current);
  }, []);

  function set(kind: roll.DocKind, name: string) {
    roll.routeTo(kind, name);
    setRoutes((r) => ({ ...r, [kind]: name }));
  }

  if (!roll.canPrintDirect()) {
    return (
      <section className="card">
        <h3>Printers</h3>
        <p className="muted">
          A browser cannot choose a printer &mdash; it always opens the print
          dialogue. Install the desktop application on this till and the labels
          come off the roll the moment a script is dispensed, with nothing to
          click.
        </p>
      </section>
    );
  }

  return (
    <section className="card">
      <h3>Printers</h3>
      <p className="muted">
        Set once. Everything printed from the dispensary then goes straight to
        the right printer with no dialogue &mdash; which is the point, because a
        dialogue at the counter is a question asked in front of a patient.
      </p>

      {loading ? (
        <p className="muted">Asking Windows what is connected…</p>
      ) : printers.length === 0 ? (
        <p className="alert warn">
          Windows reports no printers on this machine. Nothing can be printed
          directly until one is installed.
        </p>
      ) : (
        <div className="printer-routes">
          {roll.DOC_KINDS.map((d) => (
            <label key={d.kind}>
              <span className="pr-name">
                {d.name}
                <small>{d.hint}</small>
              </span>
              <select
                value={routes[d.kind] ?? ""}
                onChange={(e) => set(d.kind, e.target.value)}
              >
                {/* The empty option is not "none", it is "follow the roll" —
                    said in words, because a blank select reads as unfinished
                    and invites somebody to fill in all four. */}
                <option value="">
                  {d.kind === "label"
                    ? "— not chosen —"
                    : "Same as the dispensing label"}
                </option>
                {printers.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
              <span className="pr-going">
                {roll.printerFor(d.kind)
                  ? <>goes to <b>{roll.printerFor(d.kind)}</b></>
                  : <em>no printer &mdash; the dialogue will open</em>}
              </span>
            </label>
          ))}
        </div>
      )}

      <p className="muted small">
        The claim copy is A4 and goes through its printer&rsquo;s own driver;
        the three labels are sent as raw bytes to a thermal roll. That is why
        they are set separately &mdash; a roll cannot render a page, and a laser
        cannot interpret the bytes a roll speaks.
      </p>
    </section>
  );
}
