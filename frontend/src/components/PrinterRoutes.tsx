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

import { errorText } from "../api";
import { usePharmacy } from "../hooks/usePharmacy";
import * as roll from "../shellPrinter";
import { useToast } from "./Toast";

/** One sticker with every field filled in, so a till can prove its printer and
 *  its paper size without dispensing a real medicine to do it. Deliberately
 *  long in the fields that overflow — a test label that fits where a real one
 *  would not has proved the wrong thing. */
const TEST_LABEL = {
  patient_name: "Test Patient, Not A Real One",
  patient_id_number: "", rx_number: "RX-TEST-0000",
  product_name: "TEST LABEL, NOT A MEDICINE",
  strength: "500MG", dosage_form: "Tablet", quantity: 30,
  dosage_instructions: "THIS IS A TEST LABEL. NOTHING HAS BEEN DISPENSED "
    + "AND NOTHING SHOULD BE TAKEN.",
  warnings: "", schedule: 0, schedule_code: "",
  batch_number: "TEST", manufacturer: "",
  expiry_date: null, repeats_remaining: 0, next_repeat_date: null,
  doctor_name: "Test Prescriber", doctor_practice_no: "000000",
  dispensed_by: "Test", dispensed_at: new Date().toISOString(),
  pharmacy_name: "", pharmacy_reg_no: "", pharmacy_address: "",
  pharmacy_phone: "", branch_code: "", branch_name: "", branch_address: "",
  branch_phone: "", branch_reg_no: "", item_number: 1, item_count: 1,
} as unknown as Parameters<typeof roll.printLabelsDirect>[0][number];

export default function PrinterRoutes() {
  const [printers, setPrinters] = useState<string[]>([]);
  const [detail, setDetail] = useState<roll.PrinterInfo[]>([]);
  const [routes, setRoutes] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<roll.LabelMode>(roll.labelMode());
  const [paper, setPaper] = useState(roll.sticker());
  const [testing, setTesting] = useState(false);
  const toast = useToast();
  const pharmacy = usePharmacy();

  function save(wide: number, tall: number) {
    const next = { wide: wide > 0 ? wide : paper.wide, tall: tall > 0 ? tall : paper.tall };
    roll.setSticker(next.wide, next.tall);
    setPaper(next);
  }

  async function testLabel() {
    setTesting(true);
    try {
      await roll.printLabelsDirect([{
        ...TEST_LABEL,
        // The pharmacy's own name, so the test proves the foot of a real
        // label rather than an empty one.
        pharmacy_name: pharmacy.name, branch_name: pharmacy.name,
      }]);
      toast.ok("A test label has been sent. Check what came off the roll.");
    } catch (e) {
      toast.error(errorText(e, "The printer would not take the test label."));
    } finally {
      setTesting(false);
    }
  }

  useEffect(() => {
    roll.listPrinterInfo()
      .then((found) => { setDetail(found); setPrinters(found.map((p) => p.name)); })
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

  // What the label roll says about itself. A driver called
  // "ZDesigner ZD421-203dpi ZPL" has already answered the question this
  // setting used to ask, so the answer is shown rather than requested.
  const labelRoll = roll.printerFor("label");
  const labelDriver = detail.find((p) => p.name === labelRoll)?.driver ?? "";
  const spoken = labelRoll && roll.languageOf(labelRoll, labelDriver) === "zpl"
    ? `ZPL at ${roll.dpiOf(labelRoll, labelDriver)} dpi`
    : "";

  if (!roll.canPrintDirect()) {
    return (
      <section className="card">
        <h3>Printers</h3>
        <p className="muted">
          A browser cannot choose a printer. It always opens the print
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
        the right printer with no dialogue. Which is the point, because a
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
                {/* The empty option is not "none", it is "follow the roll".
                    Said in words, because a blank select reads as unfinished
                    and invites somebody to fill in all four. */}
                <option value="">
                  {d.kind === "label"
                    ? "not chosen."
                    : "Same as the dispensing label"}
                </option>
                {printers.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
              <span className="pr-going">
                {roll.printerFor(d.kind)
                  ? <>goes to <b>{roll.printerFor(d.kind)}</b></>
                  : <em>no printer. The dialogue will open</em>}
              </span>
            </label>
          ))}
        </div>
      )}

      {/* HOW THE LABEL REACHES THE PAPER, and how big the paper is.
          Two settings that belong to the machine rather than to the pharmacy:
          the roll is plugged into this till and is whatever size somebody
          loaded. Getting either wrong is the difference between a label and a
          blank sticker, so both say plainly what they are for. */}
      {printers.length > 0 && (
        <div className="printer-paper">
          <label>
            <span className="pr-name">
              The label printer speaks
              <small>
                {spoken
                  ? `Windows calls this printer ${labelDriver || labelRoll}, `
                    + `so the label is sent as ${spoken}. Nothing to set.`
                  : "Worked out from the printer's own driver, which is what "
                    + "names its language. Change it only if a test label "
                    + "comes out blank or as rubbish."}
              </small>
            </span>
            <select value={mode} onChange={(e) => {
              const next = e.target.value as roll.LabelMode;
              roll.setLabelMode(next); setMode(next);
            }}>
              <option value="auto">Whatever it says it speaks{spoken ? ` (${spoken})` : ""}</option>
              <option value="zpl">ZPL (Zebra and compatible)</option>
              <option value="page">Its own Windows driver (needs a PDF reader installed)</option>
              <option value="raw">Raw ESC/POS bytes (thermal receipt rolls)</option>
            </select>
          </label>

          {mode !== "raw" && (
            <label>
              <span className="pr-name">
                Sticker size
                <small>
                  Millimetres, as loaded. The label is drawn to this, so it is
                  the one measurement that has to match the paper.
                </small>
              </span>
              <span className="pr-size">
                <input type="number" min={20} max={210} value={paper.wide}
                       aria-label="Sticker width in millimetres"
                       onChange={(e) => save(Number(e.target.value), paper.tall)} />
                <span aria-hidden="true">&times;</span>
                <input type="number" min={15} max={300} value={paper.tall}
                       aria-label="Sticker height in millimetres"
                       onChange={(e) => save(paper.wide, Number(e.target.value))} />
                <span className="muted">Mm</span>
              </span>
            </label>
          )}

          <div className="pr-test">
            <button type="button" className="btn secondary" disabled={testing}
                    onClick={testLabel}>
              {testing ? "Printing…" : "Print a test label"}
            </button>
            <span className="muted small">
              Prints one sticker with every field filled in, so the size and the
              printer can be proved without dispensing anything.
            </span>
          </div>
        </div>
      )}

      <p className="muted small">
        The claim copy is A4 and goes through its printer&rsquo;s own driver.
        The labels go the way the setting above says, which for all but a
        receipt roll is also the driver. That is why they are set separately: a
        roll cannot render a page, and a laser cannot interpret the bytes a
        roll speaks.
      </p>
    </section>
  );
}
