/** The same medicine, stocked under other names.
 *
 *  A pharmacy carries one molecule several times: the brand, a generic, the same
 *  generic from another importer. They are separate products because they hold
 *  separate stock at separate prices, and they should stay separate, but the
 *  script in somebody's hand is for a *medicine*, and the patient is about to be
 *  told a price.
 *
 *  So this answers one question: is there another way to fill this, and what
 *  does it cost? Cheaper alternatives are listed first and the saving is the
 *  emphasis, because that is the conversation actually being had.
 *
 *  It says "not known" rather than "none" where the ingredient is missing. An
 *  empty list and an unanswerable question look identical on a screen and mean
 *  entirely different things — one is a fact about the shelf, the other is a
 *  gap in the catalogue that somebody should go and fill.
 */
import { useEffect, useState } from "react";
import { api, money } from "../api";

interface Variant {
  id: number; name: string; strength: string; pack_size: string;
  manufacturer: string; schedule: number; price: number;
  difference: number; on_hand: number; same_strength: boolean;
}
interface Reply {
  product: string; molecule: string; known: boolean; reason: string;
  this_price?: number; variants: Variant[];
}

export default function Variants({ productId }: { productId: number }) {
  const [data, setData] = useState<Reply | null>(null);

  useEffect(() => {
    let live = true;
    setData(null);
    // An id that is not a number never becomes a URL. Interpolating `undefined`
    // produces a real-looking request for /api/products/undefined/variants,
    // which the server rejects with a 422 that reads like a server fault rather
    // than a caller passing nothing.
    if (!Number.isFinite(productId)) return () => { live = false; };
    api.get<Reply>(`/api/products/${productId}/variants`)
      .then((r) => { if (live) setData(r); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [productId]);

  if (!data) return null;

  if (!data.known) {
    return (
      <p className="vr-none">
        No active ingredient recorded, so alternatives cannot be worked out.
      </p>
    );
  }
  if (data.variants.length === 0) {
    return (
      <p className="vr-none">
        The only {data.molecule} on the shelf.
      </p>
    );
  }

  return (
    <div className="vr">
      <p className="vr-head">
        Same medicine ({data.molecule}). {data.variants.length} other
        {data.variants.length === 1 ? "" : "s"} stocked
      </p>
      <ul className="vr-list">
        {data.variants.map((v) => (
          <li key={v.id} className={v.on_hand <= 0 ? "is-out" : ""}>
            <span className="vr-name">
              {v.name}
              {v.strength && <span className="muted"> {v.strength}</span>}
              {/* A different strength is not a swap somebody should make without
                  thinking, so it is called out rather than blended in. */}
              {!v.same_strength && v.strength && (
                <span className="badge warn">different strength</span>
              )}
            </span>
            <span className="vr-price">
              {money(v.price)}
              {Math.abs(v.difference) >= 0.005 && (
                <span className={v.difference < 0 ? "vr-cheaper" : "vr-dearer"}>
                  {v.difference < 0
                    ? ` ${money(Math.abs(v.difference))} cheaper`
                    : ` ${money(v.difference)} more`}
                </span>
              )}
            </span>
            <span className={`vr-stock${v.on_hand <= 0 ? " cu-diff" : ""}`}>
              {v.on_hand > 0 ? `${v.on_hand} in stock` : "none in stock"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
