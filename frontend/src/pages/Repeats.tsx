/** Repeats due, and a quick price.
 *
 *  Two counter jobs that share a screen because they share a moment: the phone
 *  is in the pharmacist's hand either way. One is outbound — who is due and can
 *  be served today. The other is inbound — a patient asking what something will
 *  cost them before they commit to collecting it.
 *
 *  A chronic patient who has not collected is not a missed sale, it is a patient
 *  not taking their medicine. The list is ordered the way somebody would work
 *  down it: overdue first, then soonest, and stock already checked so nobody
 *  telephones a patient they cannot serve.
 */
import { useEffect, useState } from "react";
import { api, fmtDate, money, prefetchRoute, errorText  } from "../api";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import RowLink, { RowActions } from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import Checkbox from "../components/Checkbox";
import Pagination from "../components/Pagination";
import { useClientPage } from "../hooks/useClientPage";
import Select from "../components/Select";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";

interface DueItem {
  prescription_id: number; rx_number: string; item_id: number;
  patient_id: number; patient_name: string; patient_phone: string;
  product_id: number; product: string; quantity: number; supply_days: number;
  repeats_used: number; repeats_allowed: number; repeats_left: number;
  due_on: string; days_overdue: number; overdue: boolean;
  in_stock: number; can_supply: boolean;
}
interface Due { as_at: string; count: number; overdue: number; items: DueItem[] }

interface Quote {
  product: string; quantity: number; classification: string; route: string;
  requires_prescription: boolean; cash_price: number; scheme: string;
  scheme_price: number; dispensing_fee: number; scheme_pays: number;
  patient_pays: number; levy: number; in_stock: number; can_supply: boolean;
  note: string;
}

type Tab = "due" | "price";

export default function Repeats() {
  const [due, setDue] = useState<Due | null>(null);
  // The endpoint returns the whole call sheet — `count` and `overdue` are over
  // all of it and must stay that way — so only the render is bounded.
  const dueRows = useClientPage<DueItem>(due?.items ?? [], 25);
  const [horizon, setHorizon] = useState(14);
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const [products, setProducts] = useState<any[]>([]);
  const [aids, setAids] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState<any>(null);
  const [qty, setQty] = useState(1);
  const [aidId, setAidId] = useState<number | "">("");
  const [quote, setQuote] = useState<Quote | null>(null);

  const TABS: TabDef<Tab>[] = [
    { key: "due", label: "Repeats due", count: due?.count,
      hint: "Overdue first. The order somebody would telephone in" },
    { key: "price", label: "Quick price",
      hint: "What will this cost on my scheme?" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "due");

  function load() {
    setLoading(true);
    api
      .get<Due>(`/api/repeats/call-sheet?within_days=${horizon}` +
                (overdueOnly ? "&overdue_only=true" : ""))
      .then(setDue)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }
  useEffect(load, [horizon, overdueOnly]);
  useEffect(() => { api.get<any[]>("/api/medical-aids").then(setAids).catch(() => undefined); }, []);
  useEffect(() => {
    if (q.length < 2) { setProducts([]); return; }
    api.get<any[]>(`/api/products?q=${encodeURIComponent(q)}&limit=8`)
      .then(setProducts).catch(() => undefined);
  }, [q]);

  async function price(product: any) {
    setPick(product);
    try {
      setQuote(await api.post<Quote>("/api/quick-price", {
        product_id: product.id, quantity: qty,
        medical_aid_id: aidId === "" ? null : Number(aidId),
      }));
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }
  useEffect(() => { if (pick) price(pick); }, [qty, aidId]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Repeats</h1>
          <p className="muted">
            {due
              ? due.count
                ? `${due.count} due within ${horizon} days` +
                  (due.overdue ? `, ${due.overdue} already overdue.` : ".")
                : "Nobody is due."
              : ""}
          </p>
        </div>
      </header>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "due" && (
        <>
          <div className="dt-filters">
            <label>
              Within
              <Select
                value={String(horizon ?? "")}
                onChange={(__value) => setHorizon(Number(__value))}
                options={[{ value: String(7), label: "7 days" }, { value: String(14), label: "14 days" }, { value: String(30), label: "30 days" }, { value: String(60), label: "60 days" }]}
              />
            </label>
            <Checkbox checked={overdueOnly} onChange={setOverdueOnly}>Overdue only</Checkbox>
          </div>

          <Refreshable
            loading={loading}
            hasData={!!due?.items.length}
            skeleton={<TableSkeleton cols={6} rows={6}
              widths={["18ch", "22ch", "10ch", "10ch", "10ch", "12ch"]} />}
          >
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Patient</th><th>Medicine</th><th>Due</th>
                    <th className="num">Repeats left</th>
                    <th className="num">In stock</th><th className="actions" /></tr>
                </thead>
                <tbody>
                  {dueRows.items.map((i) => (
                    <RowLink key={i.item_id} to={`/patients/${i.patient_id}`}
                      prefetch={prefetchRoute}
                      className={i.overdue ? "row-flag" : ""}>
                      <td>
                        <EntityLink kind="patient" id={i.patient_id}>{i.patient_name}</EntityLink>
                        {i.patient_phone && (
                          <div className="muted small">{i.patient_phone}</div>
                        )}
                      </td>
                      <td>
                        <EntityLink kind="product" id={i.product_id}>{i.product}</EntityLink>
                        <div className="muted small">
                          {i.quantity} · {i.supply_days} days
                        </div>
                      </td>
                      <td>
                        {fmtDate(i.due_on)}
                        {i.overdue && (
                          <div><span className="badge warn">
                            {i.days_overdue} days overdue
                          </span></div>
                        )}
                      </td>
                      <td className="num">{i.repeats_left} of {i.repeats_allowed}</td>
                      <td className="num">{i.in_stock}</td>
                      <RowActions>
                        {/* Saying so beats letting somebody telephone a patient
                            they cannot actually serve. */}
                        {i.can_supply
                          ? <span className="badge ok">can supply</span>
                          : <span className="badge warn">not enough stock</span>}
                      </RowActions>
                    </RowLink>
                  ))}
                  {!due?.items.length && !loading && (
                    <tr><td colSpan={6} className="muted pad">Nobody is due.</td></tr>
                  )}
                </tbody>
              </table>
              <Pagination meta={dueRows.meta} onPage={dueRows.setPage} noun="repeats" />
            </div>
          </Refreshable>
        </>
      )}

      {tab === "price" && (
        <div className="quick-price">
          <div className="card">
            <label>
              Medicine
              <input value={q} autoFocus onChange={(e) => setQ(e.target.value)}
                placeholder="Start typing a product name" />
            </label>
            {products.length > 0 && (
              <ul className="pick-list">
                {products.map((p) => (
                  <li key={p.id}>
                    <BusyButton className="btn ghost sm" onClick={() => price(p)}>
                      {p.name} {p.strength}
                    </BusyButton>
                  </li>
                ))}
              </ul>
            )}
            <label>
              Quantity
              <input type="number" min={1} value={qty}
                onChange={(e) => setQty(Math.max(1, Number(e.target.value)))} />
            </label>
            <label>
              Scheme
              <Select
                value={String(aidId ?? "")}
                onChange={(__value) => setAidId(__value === "" ? "" : Number(__value))}
                options={[{ value: "", label: "Cash" }, ...aids.map((a) => ({ value: String(a.id), label: a.name }))]}
              />
            </label>
          </div>

          {quote && (
            <div className="card">
              <h3>{quote.product} × {quote.quantity}</h3>
              <p className="muted">
                {quote.classification} · {quote.route}
                {quote.requires_prescription ? " · prescription required" : ""}
              </p>
              <dl className="kv">
                <dt>Cash price</dt><dd className="num">{money(quote.cash_price)}</dd>
                {quote.scheme && (
                  <>
                    <dt>On {quote.scheme}</dt>
                    <dd className="num">{money(quote.scheme_price)}</dd>
                    <dt>Dispensing fee</dt>
                    <dd className="num">{money(quote.dispensing_fee)}</dd>
                    <dt>Scheme pays</dt><dd className="num">{money(quote.scheme_pays)}</dd>
                    <dt>Levy</dt><dd className="num">{money(quote.levy)}</dd>
                  </>
                )}
                {/* The figure the patient standing there actually asked for. */}
                <dt><strong>Patient pays</strong></dt>
                <dd className="num"><strong>{money(quote.patient_pays)}</strong></dd>
              </dl>
              <p className={quote.can_supply ? "muted small" : "alert warn"}>
                {quote.can_supply
                  ? `${quote.in_stock} in stock.`
                  : `Only ${quote.in_stock} in stock. This cannot be supplied in full today.`}
              </p>
              {quote.note && <p className="muted small">{quote.note}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
