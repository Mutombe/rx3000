/** Every code that finds this product.
 *
 *  One medicine answers to several barcodes and always has: the box, the
 *  outer, the same drug from a second importer, and whatever the wholesaler
 *  printed on the shipper. The till learns them as they are scanned — that
 *  part worked — but nothing could ever show which codes a product had
 *  acquired, or take one off.
 *
 *  Taking one off is the point. A code learned against the wrong product is
 *  silent and permanent: every future scan of that box rings up the wrong
 *  medicine, and the only sign is a stock count that will not reconcile
 *  months later. It is the sort of mistake that takes two seconds to make at
 *  a busy counter and, until now, could not be undone at all.
 *
 *  The removal is optimistic — the row goes the instant it is pressed, and
 *  comes back if the server refuses. A barcode list is short and the person
 *  looking at it is usually holding the box.
 */
import { useCallback } from "react";
import { Barcode, Trash } from "@phosphor-icons/react";
import { api } from "../api";
import BusyButton from "./BusyButton";
import { useOptimisticList, rowClass } from "../hooks/useOptimisticList";

interface Code {
  id: number; code: string; pack_size: number | null;
  label: string; source: string;
}

/** Where a code came from, in words. "epos" tells nobody anything. */
const SOURCE: Record<string, string> = {
  epos: "learned at the till",
  manual: "entered by hand",
  import: "from a price file",
  receive: "scanned on a delivery",
};

export default function ProductBarcodes({ productId }: { productId: number }) {
  const list = useOptimisticList<Code>({
    load: useCallback(async () => {
      const d = await api.get<{ primary: string; codes: Code[] }>(
        `/api/scan/codes/${productId}`);
      return d.codes ?? [];
    }, [productId]),
    key: (c) => c.id,
  });

  if (list.loading && list.items.length === 0) return null;

  return (
    <div className="card">
      <div className="card-head">
        <h3><Barcode size={16} /> Codes that find this</h3>
        <span className="muted small">
          {list.items.length === 0
            ? "None yet — the till learns them as they are scanned"
            : `${list.items.length} scanned or entered`}
        </span>
      </div>

      {list.items.length === 0 ? (
        <div className="empty">
          <b>No extra barcodes</b>
          <p>
            When somebody scans a box this system does not recognise and points
            it at this product, the code is remembered here.
          </p>
        </div>
      ) : (
        <table className="dt">
          <thead>
            <tr>
              <th>Code</th><th>Pack</th><th>Label</th><th>Where it came from</th>
              <th className="actions" />
            </tr>
          </thead>
          <tbody>
            {list.items.map((c) => (
              <tr key={c.id} className={rowClass(list.stateOf(c))}>
                <td className="mono"><b>{c.code}</b></td>
                <td>{c.pack_size || <span className="muted">—</span>}</td>
                <td>{c.label || <span className="muted">—</span>}</td>
                <td className="muted small">{SOURCE[c.source] ?? c.source}</td>
                <td className="actions">
                  <BusyButton
                    className="btn small ghost"
                    title="This code will no longer find this product"
                    onClick={() => list.remove(
                      c.id,
                      () => api.delete(`/api/scan/codes/${c.id}`),
                      `${c.code} will no longer find this product.`,
                    )}
                  >
                    <Trash size={13} />
                  </BusyButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
