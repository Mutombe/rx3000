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
import { DownloadSimple } from "@phosphor-icons/react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";

/** The datasets the server will produce. Named here so a typo is a build
 *  error rather than a 404 somebody meets at the end of a long month. */
export type Dataset =
  | "products" | "batches" | "claims" | "to-follows"
  | "journal" | "trial-balance" | "accounts";

export default function ExportButton({
  dataset, label = "Spreadsheet", className = "btn secondary small",
}: {
  dataset: Dataset;
  label?: string;
  className?: string;
}) {
  const toast = useToast();

  async function download() {
    try {
      const file = await api.blob(`/api/export/${dataset}`);
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
    <BusyButton className={className} onClick={download}>
      <DownloadSimple size={14} /> {label}
    </BusyButton>
  );
}
