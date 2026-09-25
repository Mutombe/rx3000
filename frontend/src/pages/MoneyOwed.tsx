/** Medicine that has gone out and money that has not come in.
 *
 *  A work list, not a report. Every row is a patient who took their medicine
 *  and paid part of it, and it stays here until somebody collects the rest —
 *  which is the whole reason for allowing it in the first place. A debt the
 *  software will not show you is a debt nobody chases.
 *
 *  Sorted oldest first, because the one most likely to go uncollected is the
 *  one that has been sitting longest, not the largest.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise, Phone } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "../components/BusyButton";
import { currencyWorld } from "../components/Tenders";
import { EntityLink } from "../components/Filters";
import { TableSearch, useSearch } from "../components/Filters";
import PartPayment, { PartPaymentChoice } from "../components/PartPayment";
import { useToast } from "../components/Toast";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import Person from "../components/Person";
import PageHead from "../components/PageHead";
import Th from "../components/Th";

interface Row {
  sale_id: number;
  sale_number: string;
  created_at: string;
  patient_id: number | null;
  patient: string;
  phone: string;
  total: number;
  paid: number;
  balance: number;
  days: number;
}

interface Owed {
  items: Row[];
  total_owed: number;
  patients: number;
}

export default function MoneyOwed() {
  const [data, setData] = useState<Owed | null>(null);
  const [failed, setFailed] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [collecting, setCollecting] = useState<Row | null>(null);
  const [currencyState, setCurrencyState] = useState<any>(null);
  const toast = useToast();

  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setSpinning(true);
    api.get<Owed>("/api/pos/owed")
      .then((d) => { setData(d); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "What is owed could not be worked out.")))
      .finally(() => {
        setLoading(false);
        window.setTimeout(() => setSpinning(false), 400);
      });
  }, []);
  useEffect(() => {
    api.get("/api/currency").then(setCurrencyState).catch(() => undefined);
  }, []);


  useEffect(() => { load(); }, [load]);

  /** Collecting the rest needs no authorisation — taking money in is not the
   *  decision that had to be approved; letting it go out was. */
  async function collect(row: Row, choice: PartPaymentChoice) {
    try {
      const settles = choice.amount + 0.005 >= row.balance;
      await api.post(`/api/pos/sales/${row.sale_id}/pay`, settles
        ? { payment_method: choice.method, amount_tendered: choice.amount }
        : {
            payment_method: "split",
            part_payment: true,
            part_payment_note: choice.note,
            tenders: [{ method: choice.method, currency_code: "USD", amount: choice.amount }],
          });
      toast.ok(settles
        ? `${money(choice.amount)} collected. ${row.patient} owes nothing.`
        : `${money(choice.amount)} collected. ${money(row.balance - choice.amount)} still owed.`);
      setCollecting(null);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be recorded."));
    }
  }

  const rows = data?.items ?? [];
  /* Every unpaid sale in the shop. Somebody rings about THEIR bill, so
     the question is always one name in a list that only grows. */
  const { q, setQ, shown } = useSearch(rows, (r) => [r.patient, r.phone, r.sale_number]);
  const stale = rows.filter((r) => r.days >= 30);

  return (
    <>
      <PageHead title="Money owed" sub="Medicine that has gone out and has not been paid for in full">
        <button className="btn secondary" onClick={load}>
                  <ArrowClockwise size={15} className={spinning ? "spin" : ""} />
                  Refresh
                </button>
      </PageHead>

      {failed && <div className="alert error">{failed}</div>}

      {data && (
        <div className="wc-bands">
          <div className="wl-stat">
            <b>{money(data.total_owed)}</b><span>Owed to the pharmacy</span>
          </div>
          <div className="wl-stat">
            <b>{data.patients}</b><span>patient{data.patients === 1 ? "" : "s"}</span>
          </div>
          <div className={`wl-stat${stale.length ? " wc-stale" : ""}`}>
            <b>{money(stale.reduce((s, r) => s + r.balance, 0))}</b>
            <span>Owing more than a month</span>
          </div>
        </div>
      )}

      <div className="card">
        {rows.length === 0 && !failed ? (
          <div className="empty">
            <b>Nobody owes the pharmacy anything.</b>
            <p>
              A sale appears here when a patient pays part of it and takes their
              medicine. It leaves when the balance is collected.
            </p>
          </div>
        ) : (
          <Refreshable
            loading={loading}
            hasData={!!data?.items?.length}
            skeleton={<TableSkeleton cols={7} rows={5}
              widths={["20ch", "12ch", "10ch", "10ch", "10ch", "10ch", "10ch"]} />}
          >
          <TableSearch value={q} onChange={setQ}
                       placeholder="Find a patient, a phone number or a sale…"
                       shown={shown.length} total={rows.length} />
          <table className="dt">
            <thead>
              <tr>
                <Th>Patient</Th><Th>Sale</Th><Th>Since</Th>
                <Th className="num">Sale</Th><Th className="num">Paid</Th>
                <Th className="num">Owed</Th><th className="actions" />
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.sale_id} className={r.days >= 30 ? "row-flag" : ""}>
                  <td>
                    <EntityLink kind="patient" id={r.patient_id}>
                      <Person className="strong" name={r.patient} />
                    </EntityLink>
                    {r.phone && (
                      <div className="muted small"><Phone size={11} /> {r.phone}</div>
                    )}
                  </td>
                  <td className="mono">
                    <EntityLink kind="sale" id={r.sale_id}>{r.sale_number}</EntityLink>
                  </td>
                  <td>
                    {fmtDate(r.created_at)}
                    <div className="muted small">
                      {r.days} day{r.days === 1 ? "" : "s"}
                    </div>
                  </td>
                  <td className="num">{money(r.total)}</td>
                  <td className="num">{money(r.paid)}</td>
                  <td className="num"><b>{money(r.balance)}</b></td>
                  <td className="actions">
                    <BusyButton className="small" onClick={async () => setCollecting(r)}>
                      Collect
                    </BusyButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </Refreshable>
        )}
      </div>

      {collecting && (
        <PartPayment
          owed={collecting.balance}
          patient={collecting.patient}
          {...currencyWorld(currencyState)}
          onCancel={() => setCollecting(null)}
          onConfirm={(choice) => collect(collecting, choice)}
        />
      )}
    </>
  );
}
