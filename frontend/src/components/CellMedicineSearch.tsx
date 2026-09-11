/** Swap a line's medicine from inside the table.
 *
 *  Double-clicking a medicine cell opens this in its place: a search, and the
 *  matches listed under the cell. Picking one replaces the medicine on that
 *  line and keeps everything else about it — quantity, directions, diagnosis,
 *  repeats — because a swap is most often the generic beside the brand, and
 *  retyping the directions for it is the work the swap was meant to save.
 *
 *  The list is positioned on the viewport rather than inside the cell. The
 *  table scrolls, and anything that opens inside a scrolling box is clipped at
 *  its edge: the last visible line's matches would have been cut in half.
 *
 *  Only the dispensary's own product search is used, so what can be picked here
 *  is exactly what the Medicine field above the table would offer on this route.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Product } from "../types";

export default function CellMedicineSearch({
  route, current, takenIds, onPick, onCancel, onTab,
}: {
  route: string;
  /** The medicine on the line now, shown as the placeholder. */
  current: string;
  /** Medicines already on the script; offered, but not pickable. */
  takenIds: number[];
  onPick: (product: Product) => void;
  onCancel: () => void;
  onTab: (direction: 1 | -1) => void;
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Product[]>([]);
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setHits([]); return; }
    let live = true;
    // Debounced, and the answer dropped if the typing moved on meanwhile.
    const t = window.setTimeout(() => {
      api.get<Product[]>(`/api/dispensing/products?route=${route}&q=${encodeURIComponent(term)}`)
        .then((rows) => { if (live) { setHits(rows.slice(0, 8)); setCursor(0); } })
        .catch(() => { if (live) setHits([]); });
    }, 200);
    return () => { live = false; window.clearTimeout(t); };
  }, [q, route]);

  const pickable = (p: Product) => !takenIds.includes(p.id);
  const rect = input.current?.getBoundingClientRect();

  return (
    <>
      <input
        ref={input}
        className="cell-input"
        autoFocus
        value={q}
        placeholder={current}
        aria-label={`Swap ${current}: search by name`}
        aria-expanded={hits.length > 0}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && hits.length) {
            e.preventDefault(); setCursor((c) => (c + 1) % hits.length); return;
          }
          if (e.key === "ArrowUp" && hits.length) {
            e.preventDefault(); setCursor((c) => (c - 1 + hits.length) % hits.length); return;
          }
          if (e.key === "Enter") {
            e.preventDefault();
            const p = hits[cursor];
            if (p && pickable(p)) onPick(p);
            return;
          }
          // Handled here, so the page's own Escape (which clears the script
          // when nothing is open) never sees it.
          if (e.key === "Escape") { e.preventDefault(); onCancel(); return; }
          if (e.key === "Tab") { e.preventDefault(); onTab(e.shiftKey ? -1 : 1); }
        }}
        onBlur={onCancel}
      />
      {hits.length > 0 && rect && (
        <ul className="cell-menu" role="listbox" aria-label="Medicines to swap in"
            style={{ left: rect.left, top: rect.bottom + 4, width: Math.max(rect.width, 380) }}>
          {hits.map((p, i) => {
            const taken = !pickable(p);
            return (
              <li key={p.id} role="option"
                  aria-selected={i === cursor} aria-disabled={taken}
                  className={`${i === cursor ? "on" : ""}${taken ? " is-taken" : ""}`}
                  // Taken on mousedown: the field's blur fires first on a click
                  // and would close the list out from under it.
                  onMouseDown={(e) => { e.preventDefault(); if (!taken) onPick(p); }}
                  onMouseEnter={() => setCursor(i)}>
                <span className="cell-menu-main">
                  <b>{p.name}</b> {p.strength}{" "}
                  <span className="muted">{p.dosage_form}</span>
                </span>
                <span className="muted">
                  {taken ? "already on the script" : `${p.quantity_on_hand} in stock`}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
