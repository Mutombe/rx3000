/** A pack the catalogue does not recognise, taught to it at the counter.
 *
 *  Only 4,883 of CareXpress's 16,407 lines carry a barcode, because that is all
 *  their old system had. So a dispenser scanning a real pack is told "nothing is
 *  stocked under that code" several times an hour — true, useless, and the end
 *  of the road.
 *
 *  A miss is the start of a piece of work, not the end of one. They are holding
 *  the pack and they know what it is: they pick the medicine, the code is
 *  attached to it, and the next person to scan that pack is answered. A pharmacy
 *  teaches its own catalogue in about a week of ordinary work, with nobody
 *  sitting down to do data entry.
 *
 *  The till has done this since the scan path was written. This is the same
 *  thing on the screen where packs are actually handled.
 */
import { useEffect, useRef, useState } from "react";
import { Barcode, MagnifyingGlass, Warning } from "@phosphor-icons/react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";
import { Product } from "../types";

export default function AttachBarcode({
  code, route, onClose, onAttached,
}: {
  /** What was scanned and not recognised. */
  code: string;
  /** Which medicines this screen may offer, so a scan cannot go round the tab. */
  route?: string;
  onClose: () => void;
  /** The product the code now belongs to, ready to go on the script. */
  onAttached: (product: Product) => void;
}) {
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Product[]>([]);
  const [picked, setPicked] = useState<Product | null>(null);
  const first = useRef<HTMLInputElement | null>(null);

  useEffect(() => { window.setTimeout(() => first.current?.focus(), 60); }, []);

  useEffect(() => {
    const term = query.trim();
    if (term.length < 2) { setHits([]); return; }
    let live = true;
    const t = window.setTimeout(() => {
      api.get<Product[]>(`/api/dispensing/products?${route ? `route=${route}&` : ""}`
        + `q=${encodeURIComponent(term)}&limit=8`)
        .then((r) => { if (live) setHits(r); })
        .catch(() => { if (live) setHits([]); });
    }, 180);
    return () => { live = false; window.clearTimeout(t); };
  }, [query, route]);

  async function attach() {
    if (!picked) return;
    try {
      const said = await api.post<{ message?: string }>("/api/scan/link", {
        code, product_id: picked.id,
      });
      toast.ok(said?.message || `${picked.name} now answers to that code.`);
      onAttached(picked);
      onClose();
    } catch (e) {
      // Already another product's code: that is worth reading, not retrying.
      toast.error(errorText(e));
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true"
         aria-labelledby="attach-title" onClick={onClose}>
      <div className="modal attach-modal" onClick={(e) => e.stopPropagation()}>
        <h2 id="attach-title">Which medicine is this?</h2>
        <p className="muted">
          Nothing is stocked under <span className="mono">{code}</span> yet. Say what is in
          your hand and the code is kept, so the next person who scans this pack is
          answered instead of searching.
        </p>

        <div className="field">
          <label htmlFor="attach-find">The medicine on the pack</label>
          <div className="attach-find">
            <MagnifyingGlass size={14} />
            <input id="attach-find" ref={first} value={query}
                   placeholder="Search by name…"
                   onChange={(e) => { setQuery(e.target.value); setPicked(null); }} />
          </div>
        </div>

        {picked ? (
          <p className="attach-picked">
            <Barcode size={16} />
            <span>
              <b>{picked.name}</b> {picked.strength}
              <span className="muted"> will answer to {code}</span>
            </span>
            <button type="button" className="linkish" onClick={() => setPicked(null)}>
              Choose another
            </button>
          </p>
        ) : (
          <div className="attach-hits">
            {hits.map((p) => (
              <button key={p.id} type="button" className="product-pick"
                      onClick={() => setPicked(p)}>
                <span><b>{p.name}</b> {p.strength}</span>
                <span className="muted">
                  {p.here ?? p.quantity_on_hand ?? 0} in stock
                  {p.schedule ? ` · S${p.schedule}` : ""}
                </span>
              </button>
            ))}
            {query.trim().length >= 2 && hits.length === 0 && (
              <p className="muted small">
                Nothing matches that name on this tab. The pack may belong to another
                route, or the medicine may not be in the catalogue at all.
              </p>
            )}
          </div>
        )}

        <p className="fin-note is-warn">
          <Warning size={13} weight="fill" />
          <span>
            Scan the pack in your hand, not a box on the shelf: the code is kept against
            this medicine for everybody.
          </span>
        </p>

        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>Never mind</button>
          <BusyButton className="btn primary" busyLabel="Keeping it…"
                      disabled={!picked} onClick={attach}>
            Keep this code
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
