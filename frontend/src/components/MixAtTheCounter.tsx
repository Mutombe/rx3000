/** Something made up at the counter, while the patient waits.
 *
 *  The incumbent called this a free-type label: type a name, print a sticker,
 *  and nothing else in the system ever heard of it. That is fast, and it is how
 *  a recall on the menthol cannot reach the patient who was given it.
 *
 *  So this asks for the ingredients. Stock comes off each one, the preparation
 *  gets a batch number and an expiry of its own, and it takes the schedule of
 *  its strongest ingredient — a cream with tramadol in it is a schedule 5
 *  preparation, and the dispenser is told so before they make it up rather than
 *  after they have handed it over.
 *
 *  What it costs and what schedule it will be are shown while the ingredients
 *  are still being typed, because both change the decision and neither is worth
 *  discovering afterwards.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useScheduleCodes } from "../schedules";
import { MagnifyingGlass, Trash, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import BusyButton from "./BusyButton";
import Checkbox from "./Checkbox";
import SigInput from "./SigInput";
import { useToast } from "./Toast";
import { Product } from "../types";

interface Line { product: Product; quantity: string }

interface Quote {
  total_cost: number; effective_schedule: number; can_prepare: boolean;
  short_of: string[];
}

export interface MadeUp {
  product_id: number; name: string; reference: string; batch_number: string;
  expiry_date: string; schedule: number; quantity: number; unit_price: number;
  directions: string; warning: string;
}

export default function MixAtTheCounter(
  { open, onClose, onMade }: {
    open: boolean;
    onClose: () => void;
    /** The preparation, ready to go on the script as a line. */
    onMade: (made: MadeUp) => void;
  },
) {
  const sched = useScheduleCodes();
  const toast = useToast();
  const [name, setName] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Product[]>([]);
  const [makes, setMakes] = useState("1");
  const [unit, setUnit] = useState("bottle");
  const [shelfLife, setShelfLife] = useState("30");
  const [directions, setDirections] = useState("");
  const [price, setPrice] = useState("");
  const [keep, setKeep] = useState(false);
  const [quote, setQuote] = useState<Quote | null>(null);
  const first = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(""); setLines([]); setQuery(""); setHits([]); setMakes("1");
    setUnit("bottle"); setShelfLife("30"); setDirections(""); setPrice("");
    setKeep(false); setQuote(null);
    window.setTimeout(() => first.current?.focus(), 60);
  }, [open]);

  // The ingredients come from stock, so the search is the dispensary's own.
  useEffect(() => {
    const term = query.trim();
    if (term.length < 2) { setHits([]); return; }
    let live = true;
    const t = window.setTimeout(() => {
      api.get<Product[]>(`/api/dispensing/products?route=otc&q=${encodeURIComponent(term)}&limit=8`)
        .then((r) => { if (live) setHits(r); })
        .catch(() => { if (live) setHits([]); });
    }, 180);
    return () => { live = false; window.clearTimeout(t); };
  }, [query]);

  const ingredients = useMemo(
    () => lines
      .filter((l) => Number(l.quantity) > 0)
      .map((l) => ({ product_id: l.product.id, quantity: Number(l.quantity) })),
    [lines]);

  // Costed while it is still being typed: the price and the schedule both
  // change what the dispenser decides to do.
  const key = JSON.stringify(ingredients);
  useEffect(() => {
    if (!ingredients.length) { setQuote(null); return; }
    let live = true;
    api.post<Quote>("/api/compounding/at-the-counter/quote", { ingredients })
      .then((q) => { if (live) setQuote(q); })
      .catch(() => { if (live) setQuote(null); });
    return () => { live = false; };
  }, [key]);

  if (!open) return null;

  const why =
    name.trim().length < 3 ? "Give it a name the patient will read."
      : !ingredients.length ? "Add what goes into it."
        : quote && !quote.can_prepare
          ? `Not enough stock: short of ${quote.short_of.join(", ")}.`
          : Number(makes) < 1 ? "Say how many it makes."
            : "";

  async function makeItUp() {
    try {
      const made = await api.post<MadeUp>("/api/compounding/at-the-counter", {
        name: name.trim(),
        ingredients,
        makes: Number(makes) || 1,
        unit: unit.trim(),
        shelf_life_days: Number(shelfLife) || 30,
        directions: directions.trim(),
        price: Number(price) || 0,
        keep_formula: keep,
      });
      toast.ok(`${made.name} made up as ${made.reference}.`);
      onMade(made);
      onClose();
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true"
         aria-labelledby="mix-title" onClick={onClose}>
      <div className="modal mix-modal" onClick={(e) => e.stopPropagation()}>
        <h2 id="mix-title">Mix at the counter</h2>
        <p className="muted">
          Made up now, from stock. It takes a batch number and an expiry of its own, and
          the schedule of its strongest ingredient. So it is dispensed, labelled and
          recalled like anything else on the shelf.
        </p>

        <div className="field">
          <label htmlFor="mix-name">Name</label>
          <input id="mix-name" ref={first} value={name} maxLength={200}
                 placeholder="What the label will call it"
                 onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="mix-ingredients">
          <div className="mix-head">
            <span>Ingredients</span>
            <span className="muted">From stock</span>
          </div>
          {lines.map((l, i) => (
            <div className="mix-line" key={l.product.id}>
              <span className="mix-what">{l.product.name} {l.product.strength}</span>
              <input className="mix-qty" type="number" min="0" step="0.01" value={l.quantity}
                     aria-label={`How much ${l.product.name}`}
                     onChange={(e) => setLines(lines.map((x, n) =>
                       (n === i ? { ...x, quantity: e.target.value } : x)))} />
              <button type="button" className="btn ghost small"
                      aria-label={`Take ${l.product.name} out`}
                      onClick={() => setLines(lines.filter((_, n) => n !== i))}>
                <Trash size={13} />
              </button>
            </div>
          ))}
          <div className="mix-find">
            <MagnifyingGlass size={14} />
            <input value={query} placeholder="Add an ingredient…"
                   aria-label="Find an ingredient"
                   onChange={(e) => setQuery(e.target.value)} />
          </div>
          {hits.length > 0 && (
            <div className="mix-hits">
              {hits.filter((h) => !lines.some((l) => l.product.id === h.id)).map((h) => (
                <button key={h.id} type="button" className="product-pick"
                        onClick={() => {
                          setLines([...lines, { product: h, quantity: "" }]);
                          setQuery(""); setHits([]);
                        }}>
                  <span><b>{h.name}</b> {h.strength}</span>
                  <span className="muted">
                    {h.here ?? h.quantity_on_hand ?? 0} in stock
                    {h.schedule ? ` · S${h.schedule}` : ""}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mix-row">
          <div className="field">
            <label htmlFor="mix-makes">Makes</label>
            <input id="mix-makes" type="number" min="1" value={makes}
                   onChange={(e) => setMakes(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="mix-unit">Of what</label>
            <input id="mix-unit" value={unit} maxLength={40} placeholder="bottle, pot, sachet"
                   onChange={(e) => setUnit(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="mix-shelf">Shelf life</label>
            <input id="mix-shelf" type="number" min="1" value={shelfLife}
                   onChange={(e) => setShelfLife(e.target.value)} />
          </div>
        </div>

        <div className="field">
          <label htmlFor="mix-directions">Directions</label>
          <SigInput id="mix-directions" value={directions} onChange={setDirections}
                    placeholder="What the label tells the patient, e.g. apply bd prn" />
        </div>

        {/* What it costs and what it will be, while it is still being typed. */}
        <div className="mix-sum">
          <div>
            <span className="muted">Ingredients cost</span>
            <b>{quote ? money(quote.total_cost) : "none"}</b>
          </div>
          <div>
            <span className="muted">Schedule</span>
            <b>{quote ? (quote.effective_schedule
              ? sched(quote.effective_schedule) : "unscheduled") : "none"}</b>
          </div>
          <div className="field mix-price">
            <label htmlFor="mix-price">Price</label>
            <input id="mix-price" type="number" min="0" step="0.01" value={price}
                   placeholder={quote ? (quote.total_cost * 2).toFixed(2) : "0.00"}
                   onChange={(e) => setPrice(e.target.value)} />
          </div>
        </div>
        {quote && quote.effective_schedule >= 5 && (
          <p className="fin-note is-warn">
            <Warning size={13} weight="fill" />
            <span>
              A schedule {quote.effective_schedule} ingredient makes this a schedule{" "}
              {quote.effective_schedule} preparation: it is dispensed under those rules,
              and the register records what went into it.
            </span>
          </p>
        )}

        <Checkbox checked={keep} onChange={setKeep}>
          Keep the formula, for the next time it is asked for
        </Checkbox>

        {why && (
          <p className="disp-blocked"><Warning size={14} weight="fill" /><span>{why}</span></p>
        )}
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>Never mind</button>
          <BusyButton className="btn primary" busyLabel="Making it up…"
                      disabled={!!why} onClick={makeItUp}>
            Make it up
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
