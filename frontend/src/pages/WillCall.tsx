/** The will-call shelf: bagged, and nobody has come for it.
 *
 *  Every pharmacy has this shelf and no system here modelled it, so a bag nobody
 *  came back for was indistinguishable from one handed over and the only way to
 *  find it was to read the names on the shelf.
 *
 *  Ordered oldest first, deliberately. The point of the screen is the bag that
 *  has been there longest; a list opening on this morning's dispensings puts the
 *  thing you need at the bottom.
 *
 *  The band, not the day count, is what the row leads with. "Forty-one days" asks
 *  the reader to decide what that means on a Saturday morning with a queue; "over
 *  a month, return it to stock and reverse the claim" does not.
 */
import { useCallback, useEffect, useState } from "react";
import { useScheduleCodes } from "../schedules";
import { Link } from "react-router-dom";
import { Phone } from "@phosphor-icons/react";
import { api, errorText, fmtDateTime, money, prefetchRoute } from "../api";
import BusyButton from "../components/BusyButton";
import RowLink, { RowActions } from "../components/RowLink";
import { useAsk } from "../components/Confirm";
import Pagination from "../components/Pagination";
import { TableSearch, useSearch } from "../components/Filters";
import { useClientPage } from "../hooks/useClientPage";
import { useToast } from "../components/Toast";
import { TableSkeleton } from "../components/Skeleton";
import PageHead from "../components/PageHead";
import ExportButton from "../components/ExportButton";
import Th from "../components/Th";

interface Bag {
  dispensing_id: number;
  outstanding: number;
  sale_id: number | null;
  rx_number: string;
  patient_id: number | null;
  patient: string;
  phone: string;
  product: string;
  /** What the label on the bag says. */
  directions: string;
  quantity: number;
  schedule: number | null;
  dispensed_at: string;
  dispensed_by: string;
  days_waiting: number;
  band: "fresh" | "waiting" | "stale" | "abandoned";
  action: string;
  needs_id: boolean;
}

interface Shelf {
  items: Bag[];
  more: boolean;
  total: number;
  bands: Record<string, number>;
}

const BAND_LABEL: Record<string, string> = {
  fresh: "Today or yesterday",
  waiting: "Waiting",
  stale: "A week or more",
  abandoned: "Over a month",
};

export default function WillCall() {
  const sched = useScheduleCodes();
  const [shelf, setShelf] = useState<Shelf | null>(null);
  const [failed, setFailed] = useState("");
  const [band, setBand] = useState("");
  const toast = useToast();
  const ask = useAsk();

  /** THE BAND IS ASKED FOR, NOT SIFTED OUT OF WHAT ARRIVED.
   *
   *  The tiles count the whole shelf and the list held only the oldest four
   *  hundred bags, so on a shelf of 645 every one of those was stale or
   *  abandoned, and pressing "143 Waiting" answered "Nothing waiting." The
   *  count was honest; the list could not honour it. The server now narrows
   *  the rows to the band, using the same table it counts from, so the two
   *  cannot disagree.
   */
  /* 200, because that is the ceiling and asking for more is not honest.
     RequestSizeLimit clamps every `limit` in the product to MAX_PER_PAGE to
     stop one request asking for a hundred thousand rows. This asked for 400,
     was quietly cut to 200, and then showed 200 of 645 while the tile above
     said 645 — the request looked generous and the screen was short, with
     nothing saying which. */
  const load = useCallback(() =>
    api.get<Shelf>(`/api/dispensing/will-call?limit=200${
      band ? `&band=${encodeURIComponent(band)}` : ""}`)
      .then((s) => { setShelf(s); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "The shelf could not be read."))),
  [band]);

  useEffect(() => { load(); }, [load]);

  const all = shelf?.items ?? [];
  /* SOMEBODY IS STANDING AT THE COUNTER SAYING THEIR NAME.
     645 bags on the shelf and no way to look one up: the answer to "is mine
     ready" was to page through twenty-six screens of them. The band tiles
     narrow by age, which is the question the pharmacist asks; this is the
     question the customer asks. */
  const { q, setQ, shown: rows } = useSearch(all, (b) => [
    b.patient, b.phone, b.product, b.rx_number, b.dispensed_by,
  ]);
  const page = useClientPage(rows, 25);

  async function collect(bag: Bag) {
    /* ONE PROMPT, WHERE THE LAW WANTS ONE.
       A confirm stood here first and collected nothing: for an ordinary bag it
       restated the row the person had just pressed and asked them to agree
       with it, and for a controlled one it was a preamble to the prompt below
       that actually takes the record. Handing over is the busiest action on
       this shelf and it is reversible — `uncollect` puts the bag back, dated
       from the dispensing — so a modal per hand-over bought nothing and cost a
       click every time. The name prompt below still stands, because that one
       is the legal record rather than a courtesy. */

    // Who took it, asked properly. This was a `window.prompt` — an unstyled
    // operating-system box with no label and no way to require an answer —
    // collecting the legal record of who received a controlled substance.
    // Cancel returned an empty string indistinguishable from a blank answer,
    // so the only thing standing between a schedule 6 handover and no name at
    // all was a toast after the fact.
    let takenBy = "";
    if (bag.needs_id) {
      const answer = await ask({
        title: `Who is taking ${bag.product}?`,
        body: (
          <>
            This is a Schedule {bag.schedule} item. The name of whoever
            physically receives it is part of the record, and it is the answer
            to "who had it" if the question is ever asked.
          </>
        ),
        field: "Name, as given",
        placeholder: "Full name",
        required: true,
        maxLength: 120,
        confirmLabel: "Record the handover",
      });
      if (!answer.ok) return;
      takenBy = answer.value;
    }
    try {
      await api.post(`/api/dispensing/will-call/${bag.dispensing_id}/collect`,
                     { taken_by: takenBy, id_seen: "" });
      toast.ok(`${bag.product} handed over.`);
      await load();
    } catch (e) {
      toast.error(errorText(e, "That could not be recorded."));
    }
  }

  /** Tell everybody in view that their medicine is waiting.
   *
   *  THE ACTION THIS SCREEN ALREADY ADVISES AND COULD NOT TAKE.
   *
   *  Every row on this shelf carries a sentence telling the reader what to do
   *  about it, and past a week that sentence is "worth a telephone call". A
   *  hundred and forty of them is a morning nobody has, so it was not done,
   *  and a bag nobody rang about becomes a bag returned to stock and a claim
   *  reversed. The message costs a few cents and saves the dispensing.
   *
   *  Sent one at a time rather than as one call, because there is no bulk
   *  endpoint and inventing one to save a round trip would hide a partial
   *  failure. Counted, so what comes back is the truth.
   */
  async function textEveryone() {
    const reachable = rows.filter((b) => b.phone.trim());
    const without = rows.length - reachable.length;
    if (!reachable.length) {
      toast.warn(rows.length
        ? "None of these have a telephone number on file, so they have to be rung by hand."
        : "There is nobody on the shelf to tell.");
      return;
    }
    const ok = await ask({
      title: `Tell ${reachable.length} ${reachable.length === 1 ? "person" : "people"} their medicine is ready?`,
      body: (
        <>
          <p>
            Each of them gets one message saying what is bagged for them and
            asking them to come in. It goes to the number on their profile.
          </p>
          {without > 0 && (
            <p className="muted">
              {without} of the {rows.length} have no number on file and are
              skipped. They stay on the list to be rung by hand.
            </p>
          )}
          {/* THE SHELF IS BIGGER THAN THE PAGE, AND THIS SAYS SO.
              The list holds the two hundred oldest bags and the tile above
              counts the whole shelf, so a button reading "Tell 200" on a shelf
              of 658 is one somebody presses believing everybody has been told.
              Which 200 is not a detail: they are the oldest, which is the
              right two hundred, and that is worth saying out loud. */}
          {shelf?.more && (
            <p className="muted">
              These are the {rows.length} that have been waiting longest, of{" "}
              {shelf.total} on the shelf. Telling the rest means asking again
              once these are handed over, or narrowing to a band above.
            </p>
          )}
        </>
      ),
      confirmLabel: `Send ${reachable.length}`,
    });
    if (!ok) return;

    let sent = 0;
    const failedFor: string[] = [];
    for (const bag of reachable) {
      try {
        await api.post("/api/messages", {
          patient_id: bag.patient_id,
          channel: "sms",
          subject: "Your medicine is ready",
          body: `Good day ${bag.patient}. Your ${bag.product} is bagged and `
              + `waiting for you at the pharmacy. Please come in when you can.`,
        });
        sent += 1;
      } catch {
        failedFor.push(bag.patient);
      }
    }
    if (failedFor.length) {
      toast.warn(`${sent} sent. ${failedFor.length} did not go: `
                 + failedFor.slice(0, 3).join(", ")
                 + (failedFor.length > 3 ? ` and ${failedFor.length - 3} more.` : "."));
    } else {
      toast.ok(`${sent} ${sent === 1 ? "person has" : "people have"} been told.`);
    }
  }

  return (
    <>
      <PageHead
        title="Will call"
        sub="Dispensed, bagged and not yet collected. Oldest first"
        count={shelf ? `${shelf.total.toLocaleString()} on the shelf` : undefined}
        // The shelf as the sheet a morning of telephone calls is worked from,
        // with the number, the days waiting and what the label says on it. A
        // pharmacy works this list away from the screen more often than on it.
        take={<ExportButton dataset="will-call" />}
        /* Whoever is in view is who gets told, so a band tile or the search
           above narrows it. The count is in the label because "tell them" on a
           shelf of six hundred is a button nobody dares press. */
        also={rows.length ? (
          <BusyButton className="btn secondary" onClick={textEveryone}
                      busyLabel="Telling them…">
            <Phone size={14} /> Tell {rows.length} it is ready
          </BusyButton>
        ) : undefined}
      />

      {failed && <div className="alert error">{failed}</div>}

      {/* The bands are the summary and the filter at once. Counted over the whole
          shelf rather than the visible page. */}
      <div className="wc-bands">
        <button className={`wl-stat${band === "" ? " is-on" : ""}`} onClick={() => setBand("")}>
          <b>{shelf?.total ?? "none"}</b><span>On the shelf</span>
        </button>
        {["fresh", "waiting", "stale", "abandoned"].map((b) => (
          <button key={b} className={`wl-stat wc-${b}${band === b ? " is-on" : ""}`}
                  onClick={() => setBand(band === b ? "" : b)}>
            <b>{shelf?.bands?.[b] ?? 0}</b><span>{BAND_LABEL[b]}</span>
          </button>
        ))}
      </div>

      <div className="card">
        {!shelf && !failed && <TableSkeleton cols={6} rows={7} rowHeight={84} />}
        {/* Two different empties, said differently.
            A filtered view with nothing in it is a filter result and should offer
            the way back out. An empty shelf is an achievement and should read
            like one. "No results" under a heading called Will call tells a
            pharmacist nothing about whether the feature is working, whether they
            have set it up, or whether they are simply on top of their bags. */}
        {shelf && rows.length === 0 && band && (
          <div className="empty">
            <b>Nothing {BAND_LABEL[band].toLowerCase()}.</b>
            <p>
              {shelf.total > 0
                ? `${shelf.total} bag${shelf.total === 1 ? " is" : "s are"} waiting in other bands.`
                : "The shelf is empty altogether."}
            </p>
            <button className="btn secondary small" onClick={() => setBand("")}>
              Show the whole shelf
            </button>
          </div>
        )}
        {shelf && rows.length === 0 && !band && (
          <div className="empty">
            <b>Nothing is waiting to be collected.</b>
            <p>
              Every bag dispensed has been handed over. Anything dispensed from
              now on appears here until somebody marks it collected, and a bag
              still here after a week is worth a telephone call.
            </p>
          </div>
        )}
        {rows.length > 0 && (
          <>
            {/* Said once, for the band in view. */}
            {band && rows[0] && (
              <p className="muted wc-advice">{rows[0].action}</p>
            )}
            <TableSearch value={q} onChange={setQ}
                         placeholder="Find a patient, a phone number or a medicine…"
                         shown={rows.length} total={all.length} />
            {/* THE SHELF IS LONGER THAN THE PAGE, AND IT SAYS SO.
                A list that stops at 200 without a word reads as the whole
                shelf, and the tiles above it say 645. The bands and the search
                are how somebody reaches the rest, so the line that admits the
                limit is also the line that points at the way round it. */}
            {shelf?.more && (
              <p className="muted small wc-more">
                Showing the oldest {all.length} of{" "}
                {band ? `${shelf.bands?.[band] ?? "more"} in this band`
                      : `${shelf.total} on the shelf`}.
                Press a band above, or search, to reach the rest.
              </p>
            )}
            <div className="dt-scroll">
              <table className="dt dt-wide">
                <thead>
                  <tr>
                    <Th className="col-name">Patient</Th><Th className="col-med">Medicine</Th><Th className="num">Qty</Th>
                    <Th>Bagged</Th><Th>Waiting</Th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((b) => (
                    // The whole row opens the bag, not just the medicine's
                    // name. A counter is read at a glance with a queue waiting,
                    // and asking somebody to aim at one word in six columns is
                    // the difference between a table that answers questions and
                    // one nobody opens. The patient link and the hand-over
                    // button keep their own destinations.
                    <RowLink key={b.dispensing_id} to={`/will-call/${b.dispensing_id}`}
                             prefetch={prefetchRoute}>
                      <td>
                        {b.patient_id
                          ? <Link to={`/patients/${b.patient_id}`}>{b.patient}</Link>
                          : b.patient}
                        {b.phone && (
                          <div className="muted small">
                            <Phone size={11} /> {b.phone}
                          </div>
                        )}
                      </td>
                      <td>
                        <b>{b.product}</b>
                        {b.needs_id && <span className="badge sched">{sched(b.schedule)}</span>}
                        {/* What is on the label, where the bag is handed over:
                            the question asked at the counter is how to take it,
                            and the shelf could not answer it. */}
                        {b.directions && (
                          <div className="wc-directions">{b.directions}</div>
                        )}
                        <div className="muted small">{b.rx_number} · {b.dispensed_by}</div>
                        {b.outstanding > 0.005 && (
                          <div className="muted small"><b>{money(b.outstanding)} to pay</b></div>
                        )}
                      </td>
                      <td className="num">{b.quantity}</td>
                      <td>{fmtDateTime(b.dispensed_at)}</td>
                      <td>
                        {/* The band leads, not the number. "Forty-one days" asks
                            the reader to decide what that means on a Saturday
                            morning with a queue behind them. */}
                        {/* The action is on the badge, not under every row.
                            It is identical for every bag in a band, so printing
                            it ten times is ten copies of one sentence competing
                            with the names, and it was too long for the column,
                            so each copy was also cut off mid-clause. */}
                        <span className={`badge wc-badge wc-${b.band}`} data-tip={b.action}>
                          {BAND_LABEL[b.band]}
                        </span>
                      </td>
                      <RowActions>
                        <BusyButton className="btn small" onClick={() => collect(b)}>
                          Handed over
                        </BusyButton>
                      </RowActions>
                    </RowLink>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination meta={page.meta} onPage={page.setPage} />
          </>
        )}
      </div>
    </>
  );
}
