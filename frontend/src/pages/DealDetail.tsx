import { FormEvent, useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money, errorText  } from "../api";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Avatar, Highlights, Path } from "../components/record";
import { Deal, Product, Quote, TimelineEntry } from "../types";
import IconButton from "../components/IconButton";
import {
  ArrowLeft,
  CalendarBlank,
  CheckSquare,
  PencilSimpleLine,
  PhoneCall,
} from "@phosphor-icons/react";
import BusyButton from "../components/BusyButton";

type Tab = "lines" | "quotes" | "activity";

/** The forward path; "lost" is an exit, not a step, so it sits outside the chevrons. */
const PATH_STAGES = [
  { key: "new", label: "New" },
  { key: "qualified", label: "Qualified" },
  { key: "proposal", label: "Proposal" },
  { key: "negotiation", label: "Negotiation" },
  { key: "won", label: "Closed won" },
];

export default function DealDetail() {
  const { id } = useParams();
  const [deal, setDeal] = useState<Deal | null>(null);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [productQ, setProductQ] = useState("");
  const [line, setLine] = useState({ product_id: 0, description: "", quantity: 1, unit_price: 0, discount_percent: 0 });
  const [note, setNote] = useState("");
  const [taskSubject, setTaskSubject] = useState("");
  const [taskDue, setTaskDue] = useState("");
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "lines", label: "Line items", count: deal?.items.length },
    { key: "quotes", label: "Quotations", count: quotes.length },
    { key: "activity", label: "Activity", count: timeline.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "lines");

  function load() {
    api.get<Deal>(`/api/crm/deals/${id}`).then(setDeal).catch((e) => toast.error(errorText(e)));
    api.get<Quote[]>(`/api/crm/deals/${id}/quotes`).then(setQuotes);
    api.get<TimelineEntry[]>(`/api/crm/timeline?deal_id=${id}`).then(setTimeline);
  }
  useEffect(load, [id]);

  useEffect(() => {
    if (productQ.length < 2) { setProducts([]); return; }
    api.get<Product[]>(`/api/products?q=${encodeURIComponent(productQ)}&limit=8`).then(setProducts);
  }, [productQ]);

  async function addLine(e: FormEvent) {
    e.preventDefault();
    try {
      const updated = await api.post<Deal>(`/api/crm/deals/${id}/items`, {
        product_id: line.product_id || null, description: line.description,
        quantity: Number(line.quantity) || 1, unit_price: Number(line.unit_price) || 0,
        discount_percent: Number(line.discount_percent) || 0,
      });
      setDeal(updated);
      setLine({ product_id: 0, description: "", quantity: 1, unit_price: 0, discount_percent: 0 });
      setProductQ("");
    } catch (err: any) { toast.error(errorText(err)); }
  }

  async function removeLine(itemId: number) {
    try { setDeal(await api.delete<Deal>(`/api/crm/deals/${id}/items/${itemId}`)); }
    catch (e: any) { toast.error(errorText(e)); }
  }

  async function moveStage(stage: string) {
    let lost_reason = "";
    if (stage === "lost") lost_reason = window.prompt("Why was this deal lost?") ?? "";
    try {
      await api.post(`/api/crm/deals/${id}/stage`, { stage, lost_reason });
      load();
    } catch (e: any) { toast.error(errorText(e)); }
  }

  async function createQuote() {
    try {
      await api.post(`/api/crm/deals/${id}/quotes`, { valid_days: 30 });
      load();
    } catch (e: any) { toast.error(errorText(e)); }
  }

  async function setQuoteStatus(quote: Quote, status: string) {
    try {
      await api.post(`/api/crm/quotes/${quote.id}/status?status=${status}`);
      load();
    } catch (e: any) { toast.error(errorText(e)); }
  }

  async function addNote(e: FormEvent) {
    e.preventDefault();
    if (!note.trim()) return;
    await api.post("/api/crm/activities", {
      activity_type: "note", subject: note, deal_id: Number(id),
      company_id: deal?.company_id ?? null, contact_id: deal?.contact_id ?? null,
    });
    setNote(""); load();
  }

  async function addTask(e: FormEvent) {
    e.preventDefault();
    if (!taskSubject.trim()) return;
    await api.post("/api/crm/activities", {
      activity_type: "task", subject: taskSubject,
      due_at: taskDue ? `${taskDue}T09:00:00` : null, deal_id: Number(id),
      company_id: deal?.company_id ?? null, contact_id: deal?.contact_id ?? null,
    });
    setTaskSubject(""); setTaskDue(""); load();
  }

  function printQuote(quote: Quote) {
    if (!deal) return;
    const rows = deal.items.map((i) =>
      `<tr><td>${i.description}</td><td class="r">${i.quantity}</td><td class="r">${money(i.unit_price)}</td>` +
      `<td class="r">${i.discount_percent ? i.discount_percent + "%" : "—"}</td><td class="r">${money(i.line_total)}</td></tr>`).join("");
    const win = window.open("", "_blank", "width=800,height=900");
    if (!win) return;
    win.document.write(`<!doctype html><html><head><title>${quote.quote_number}</title><style>
      body{font-family:Arial,Helvetica,sans-serif;padding:36px;color:#111}
      h1{margin:0 0 4px;font-size:22px} .muted{color:#666;font-size:12px}
      table{width:100%;border-collapse:collapse;margin-top:22px;font-size:13px}
      th{text-align:left;border-bottom:2px solid #111;padding:7px 6px;font-size:11px;text-transform:uppercase}
      td{padding:7px 6px;border-bottom:1px solid #ddd} .r{text-align:right}
      .totals{margin-top:18px;margin-left:auto;width:280px} .totals td{border:none;padding:4px 6px}
      .grand{font-weight:bold;font-size:16px;border-top:2px solid #111}
      .terms{margin-top:26px;font-size:12px;color:#444}</style></head><body>
      <h1>Quotation ${quote.quote_number}</h1>
      <div class="muted">Version ${quote.version} · Issued ${fmtDate(quote.created_at)}${quote.valid_until ? ` · Valid until ${fmtDate(quote.valid_until)}` : ""}</div>
      <div class="muted" style="margin-top:10px">
        <b>${deal.company?.name ?? ""}</b>${deal.contact ? `<br>Attention: ${deal.contact.first_name} ${deal.contact.last_name}` : ""}
      </div>
      <div style="margin-top:16px"><b>Re: ${deal.title}</b></div>
      <table><thead><tr><th>Description</th><th class="r">Qty</th><th class="r">Unit</th><th class="r">Disc.</th><th class="r">Total</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <table class="totals">
        <tr><td>Subtotal (excl. VAT)</td><td class="r">${money(quote.subtotal)}</td></tr>
        <tr><td>VAT</td><td class="r">${money(quote.vat_amount)}</td></tr>
        <tr class="grand"><td>Total</td><td class="r">${money(quote.total)}</td></tr>
      </table>
      <div class="terms">${quote.terms}</div></body></html>`);
    win.document.close(); win.focus();
    setTimeout(() => { win.print(); win.close(); }, 250);
  }

  if (!deal) return <DetailSkeleton
        trail={[{ label: "Dashboard", to: "/" }, { label: "Pipeline", to: "/pipeline" }, { label: "This record" }]}
        eyebrow="Opportunity"
        tabs={["Line items", "Quotations", "Activity"]}
        cards={3}
        table={5}
      />;

  return (
    <>
      <Breadcrumbs trail={[{ label: "Dashboard", to: "/" }, { label: "Pipeline", to: "/pipeline" }, { label: "This record" }]} />
      <div className="page-head">
        <div className="record-title">
          <Avatar first={deal.company?.name ?? deal.title} last="" size={44}
            label={deal.company?.name ?? "No account"} />
          <div>
            <div className="eyebrow">Opportunity</div>
            <h1>{deal.title}</h1>
            <div className="sub">
              {deal.company?.name ?? "No account"}
              {deal.contact && ` · ${deal.contact.first_name} ${deal.contact.last_name}`}
              {" · "}owner {deal.owner?.full_name ?? "unassigned"}
            </div>
          </div>
        </div>
        <Link to="/pipeline" className="btn secondary"><ArrowLeft size={13} weight="bold" /> Opportunities</Link>
      </div>

      <div className="card record-hero">
        <Path stages={PATH_STAGES} current={deal.stage} lostKey="lost" onPick={moveStage} />
        <Highlights items={[
          { label: "Deal value", value: money(deal.value), hint: `${deal.items.length} line item(s)` },
          { label: "Weighted", value: money(deal.value * deal.probability / 100), hint: `${deal.probability}% probability` },
          { label: "Expected close", value: deal.expected_close_date ? fmtDate(deal.expected_close_date) : "Not set",
            hint: deal.source ? `source: ${deal.source}` : "no source" },
          { label: "Quotes", value: String(quotes.length), hint: quotes[0]?.status ?? "none issued" },
          { label: "Stage", value: deal.stage, hint: deal.lost_reason || "—" },
        ]} />
        {deal.stage !== "lost" && (
          <div className="record-exit">
            <BusyButton className="secondary small" onClick={() => moveStage("lost")}>Mark closed lost</BusyButton>
            <span className="muted">Closing lost asks for a reason and logs it to the timeline</span>
          </div>
        )}
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "lines" && (
          <div className="card">
            <h3>Line items</h3>
            <table>
              <thead><tr><th>Description</th><th className="num">Qty</th><th className="num">Unit</th><th className="num">Disc.</th><th className="num">Total</th><th className="actions" /></tr></thead>
              <tbody>
                {deal.items.map((i) => (
                  <tr key={i.id}>
                    <td>{i.description}</td>
                    <td className="num">{i.quantity}</td>
                    <td className="num">{money(i.unit_price)}</td>
                    <td className="num">{i.discount_percent ? `${i.discount_percent}%` : "—"}</td>
                    <td className="num"><b>{money(i.line_total)}</b></td>
                    <td className="right"><IconButton action="remove" danger title="Remove this line" onClick={() => removeLine(i.id)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {deal.items.length === 0 && <div className="empty">No line items. The deal value is entered manually</div>}

            <form onSubmit={addLine} style={{ marginTop: 14, borderTop: "1px solid rgba(28,29,27,0.08)", paddingTop: 14 }}>
              <div className="field">
                <label>Add a product</label>
                <input type="search" placeholder="Search products…" value={productQ}
                  onChange={(e) => setProductQ(e.target.value)} />
                {products.map((p) => (
                  <div key={p.id} className="product-pick" onClick={() => {
                    setLine({ ...line, product_id: p.id, description: `${p.name} ${p.strength}`.trim(), unit_price: p.unit_price });
                    setProductQ(""); setProducts([]);
                  }}>
                    <span>{p.name} {p.strength}</span>
                    <span className="muted">{money(p.unit_price)}</span>
                  </div>
                ))}
              </div>
              <div className="form-row">
                <div className="field"><label>Description</label>
                  <input value={line.description} onChange={(e) => setLine({ ...line, description: e.target.value })} /></div>
                <div className="field" style={{ maxWidth: 90 }}><label>Qty</label>
                  <input type="number" min={1} value={line.quantity}
                    onChange={(e) => setLine({ ...line, quantity: Number(e.target.value) })} /></div>
                <div className="field" style={{ maxWidth: 120 }}><label>Unit price</label>
                  <input type="number" step="0.01" value={line.unit_price}
                    onChange={(e) => setLine({ ...line, unit_price: Number(e.target.value) })} /></div>
                <div className="field" style={{ maxWidth: 100 }}><label>Disc. %</label>
                  <input type="number" min={0} max={100} value={line.discount_percent}
                    onChange={(e) => setLine({ ...line, discount_percent: Number(e.target.value) })} /></div>
              </div>
              <button type="submit" disabled={!line.description}>Add line</button>
            </form>
          </div>
      )}

      {tab === "quotes" && (
          <div className="card">
            <h3>Quotations</h3>
            <div className="toolbar">
              <button onClick={createQuote} disabled={deal.items.length === 0}>
                + Generate quote v{quotes.length + 1}
              </button>
              {deal.items.length === 0 && <span className="muted">Add line items first</span>}
            </div>
            <table>
              <thead><tr><th>Quote</th><th>Version</th><th className="num">Total</th><th>Valid until</th><th>Status</th><th className="actions" /></tr></thead>
              <tbody>
                {quotes.map((qt) => (
                  <tr key={qt.id}>
                    <td className="mono">{qt.quote_number}</td>
                    <td>v{qt.version}</td>
                    <td className="num">{money(qt.total)}</td>
                    <td className="muted">{fmtDate(qt.valid_until)}</td>
                    <td>
                      <span className={`badge ${qt.status === "accepted" ? "ok"
                        : qt.status === "declined" || qt.status === "expired" ? "danger"
                        : qt.status === "sent" ? "warn" : "muted"}`}>{qt.status}</span>
                    </td>
                    <td className="right" style={{ whiteSpace: "nowrap" }}>
                      <button className="ghost small" onClick={() => printQuote(qt)}>🖨</button>
                      {qt.status === "draft" && <BusyButton className="ghost small" onClick={() => setQuoteStatus(qt, "sent")}>Send</BusyButton>}
                      {qt.status === "sent" && (
                        <>
                          <BusyButton className="ghost small" onClick={() => setQuoteStatus(qt, "accepted")}>Accept</BusyButton>
                          <BusyButton className="ghost small" onClick={() => setQuoteStatus(qt, "declined")}>Decline</BusyButton>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {quotes.length === 0 && <div className="empty">No quotes issued yet</div>}
          </div>
      )}

      {tab === "activity" && (
        <>
          <div className="card">
            <h3>Log activity</h3>
            <form onSubmit={addNote} style={{ marginBottom: 14 }}>
              <div className="field"><label>Note</label>
                <input value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="e.g. Called the finance manager, budget confirmed" /></div>
              <button className="secondary small" type="submit">Add note</button>
            </form>
            <form onSubmit={addTask}>
              <div className="form-row">
                <div className="field"><label>Task</label>
                  <input value={taskSubject} onChange={(e) => setTaskSubject(e.target.value)}
                    placeholder="e.g. Send revised pricing" /></div>
                <div className="field" style={{ maxWidth: 170 }}><label>Due</label>
                  <input type="date" value={taskDue} onChange={(e) => setTaskDue(e.target.value)} /></div>
              </div>
              <button className="secondary small" type="submit">Add task</button>
            </form>
          </div>

          <div className="card">
            <h3>Timeline</h3>
            <table>
              <tbody>
                {timeline.map((t) => (
                  <tr key={t.id}>
                    <td style={{ width: 30 }}>
                      {t.type === "task" ? <CheckSquare size={14} />
                      : t.type === "call" ? <PhoneCall size={14} />
                      : t.type === "meeting" ? <CalendarBlank size={14} />
                      : <PencilSimpleLine size={14} />}
                    </td>
                    <td>
                      <b>{t.subject}</b>
                      {t.body && <div className="muted" style={{ fontSize: 12 }}>{t.body}</div>}
                      <div className="muted" style={{ fontSize: 11 }}>
                        {t.owner ?? "system"} · {fmtDateTime(t.created_at)}
                        {t.due_at && !t.completed_at && ` · due ${fmtDate(t.due_at)}`}
                        {t.completed_at && " · done"}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {timeline.length === 0 && <div className="empty">No activity yet</div>}
          </div>
        </>
      )}
    </>
  );
}
