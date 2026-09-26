import { useEffect, useRef, useState } from "react";
/** Take this grid away as a spreadsheet.
 *
 *  The endpoint behind it puts the reason plainly: a pharmacy manager
 *  reconciles in Excel whatever the software offers, so a report that cannot
 *  leave the system is a report they will not trust. It had seven datasets
 *  ready and no button anywhere, which made that sentence a promise the product
 *  did not keep.
 *
 *  Fetched rather than linked. A plain `<a href>` cannot carry the
 *  Authorization header, and the usual workaround — the token in the query
 *  string — writes it into every access log, proxy log and browser history it
 *  passes through.
 */
import { CaretDown, DownloadSimple } from "@phosphor-icons/react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";

/** The datasets the server will produce. Named here so a typo is a build
 *  error rather than a 404 somebody meets at the end of a long month. */
export type Dataset =
  | "products" | "batches" | "claims" | "to-follows" | "patients"
  | "money-owed" | "deliveries"
  | "journal" | "trial-balance" | "accounts"
  | "scripts" | "dispensings" | "will-call" | "repeats-due"
  | "suppliers" | "orders" | "lay-bys" | "drivers" | "shifts"
  | "payables" | "compliance" | "register" | "samples" | "count-sheet"
  | "leads" | "deals" | "tickets" | "branches";

export default function ExportButton({
  dataset, label = "Export", className = "btn secondary small",
}: {
  dataset: Dataset;
  label?: string;
  className?: string;
}) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);

  // Shut when the attention goes elsewhere. A menu left hanging over a table
  // is a menu somebody closes by clicking a row they did not mean to open.
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  async function download(format: "xlsx" | "csv") {
    setOpen(false);
    try {
      const file = await api.blob(`/api/export/${dataset}?format=${format}`);
      const url = URL.createObjectURL(file.body);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename || `${dataset}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Revoked on a delay: released immediately, Safari cancels the download
      // it has not started yet.
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      toast.error(errorText(e, "That could not be exported."));
    }
  }

  return (
    /* WHICH FILE, ASKED RATHER THAN ASSUMED.
     *
     * This said "Spreadsheet" and handed over a CSV, which is two untruths at
     * once: a CSV is not a spreadsheet, and nobody was asked. It says Export,
     * and the format is a choice — Excel first, because that is what is open
     * on the counter machine, and CSV for whatever has to swallow it next. */
    <span className="exp" ref={box}>
      <BusyButton className={className} onClick={() => setOpen((o) => !o)}
                  aria-haspopup="menu" aria-expanded={open}>
        <DownloadSimple size={14} /> {label}
        <CaretDown size={10} weight="bold" className="exp-caret" />
      </BusyButton>
      {open && (
        <span className="exp-menu" role="menu">
          <button role="menuitem" onClick={() => download("xlsx")}>
            Excel workbook
            <small>Formatted, with the header held in place</small>
          </button>
          <button role="menuitem" onClick={() => download("csv")}>
            CSV
            <small>Plain text, for another system to read</small>
          </button>
        </span>
      )}
    </span>
  );
}
