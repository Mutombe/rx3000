/** A driver's round, on the driver's own phone.
 *
 *  WHAT THIS REPLACES
 *
 *  Nothing, which is the problem. Deliveries were closed from the back office
 *  by somebody who was not at the door — a dispenser typing a name the driver
 *  read down the telephone an hour later, or at the end of the shift from
 *  memory. Every fact on a waybill was one person's account of another
 *  person's afternoon.
 *
 *  WHAT IS ON THE SCREEN AND WHAT IS NOT
 *
 *  An address, a name, a telephone number as a link, and what to collect. Not
 *  the medicine and not the record: a driver finds a house and hands over a
 *  bag, and what is in the bag is between the pharmacy and the patient.
 *
 *  ONE DROP OPEN AT A TIME
 *
 *  They are standing at one door. A list of open cards on a phone is a list
 *  where the wrong one gets signed, so the stop being worked on is the only
 *  one showing its form.
 */
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { apiBase } from "../api";
import PortalShell, { PortalDoor, PortalGone, PortalLoading, useBrand,
  usePortalPass } from "./PortalShell";
import SignaturePad from "./SignaturePad";
import "./portal.css";

interface Drop {
  id: number;
  waybill_number: string;
  recipient: string;
  address: string;
  phone: string;
  instructions: string;
  status: string;
  requires_id_check: boolean;
  to_collect: number;
  received_by: string;
  signed: boolean;
}

interface Run {
  driver: string;
  drops: Drop[];
  left: number;
  done_today: number;
  holding: number;
  cod_limit: number;
  says: string;
}

const money = (n: number) =>
  n.toLocaleString(undefined, { style: "currency", currency: "USD" });

export default function DriverPortal() {
  const { token = "" } = useParams();
  const brand = useBrand("driver", token);
  const gate = usePortalPass("driver", token);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [locked, setLocked] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(() => {
    fetch(`${apiBase}/api/portal/driver/${token}`, { headers: gate.headers })
      .then(async (r) => {
        const data = await r.json();
        if (r.status === 401) { setLocked(true); return; }
        if (!r.ok) throw new Error(data.detail ?? "This link could not be opened.");
        setLocked(false);
        setRun(data);
        // The first stop opens itself. They are on a motorbike; a list of
        // closed panels is one more tap before they can do anything.
        setOpen((was) => was ?? (data.drops as Drop[])[0]?.id ?? null);
      })
      .catch((e) => setError(e.message));
  }, [token, gate.pass]);
  useEffect(load, [load]);

  if (error && !run) return <PortalGone brand={brand} said={error} />;
  if (locked && !run) {
    return (
      <PortalDoor
        brand={brand}
        title="Your round"
        lead="Enter the code the pharmacy gave you when they sent this link."
        said={gate.said}
        busy={gate.busy}
        onCode={(code) => gate.unlock(code)}
      />
    );
  }
  if (!run) return <PortalLoading brand={brand} />;

  return (
    <PortalShell
      brand={brand}
      title={run.driver}
      sub={run.says}
      foot={"Every delivery you close here is signed for at the door and "
            + "stamped with the time. Ring the pharmacy if anything looks wrong."}
    >
      {error && <p className="pp-error">{error}</p>}

      {/* The money in their pocket, shown because it is the one number the
          shop and the driver argue about at the end of a round, and because
          a driver who can see it coming can head back before the limit. */}
      {(run.holding > 0 || run.cod_limit > 0) && (
        <section className="pp-card dp-purse">
          <div>
            <span className="pp-muted">You are carrying</span>
            <b className="pp-big">{money(run.holding)}</b>
          </div>
          {run.cod_limit > 0 && (
            <span className={`pp-pill ${run.holding > run.cod_limit
              ? "pp-pill-warn" : ""}`}>
              {run.holding > run.cod_limit
                ? `Over your ${money(run.cod_limit)} limit`
                : `Limit ${money(run.cod_limit)}`}
            </span>
          )}
        </section>
      )}

      {run.drops.length === 0 ? (
        <div className="pp-card pp-centre">
          <b>Nothing to deliver</b>
          <p className="pp-muted">
            When the pharmacy sends something out with you it will appear here.
          </p>
        </div>
      ) : (
        run.drops.map((drop) => (
          <DropCard
            key={drop.id}
            token={token}
            drop={drop}
            headers={gate.headers}
            open={open === drop.id}
            onToggle={() => setOpen(open === drop.id ? null : drop.id)}
            onDone={load}
          />
        ))
      )}
    </PortalShell>
  );
}

function DropCard({ token, drop, open, onToggle, onDone, headers }: {
  token: string;
  drop: Drop;
  open: boolean;
  onToggle: () => void;
  onDone: () => void;
  headers?: Record<string, string>;
}) {
  const [who, setWho] = useState(drop.recipient);
  const [idSeen, setIdSeen] = useState("");
  const [signature, setSignature] = useState("");
  const [reason, setReason] = useState("");
  const [failing, setFailing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [oops, setOops] = useState("");

  async function send(path: string, body: unknown) {
    setBusy(true);
    setOops("");
    try {
      const r = await fetch(
        `${apiBase}/api/portal/driver/${token}/drops/${drop.id}/${path}`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(headers ?? {}) },
          body: JSON.stringify(body),
        });
      const data = await r.json();
      if (!r.ok) {
        const d = data.detail;
        throw new Error(typeof d === "string" ? d
          : "That did not go through. Try again.");
      }
      onDone();
    } catch (e: any) {
      setOops(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`pp-card dp-drop${drop.requires_id_check ? " is-id" : ""}`}>
      <button type="button" className="dp-head" onClick={onToggle}
              aria-expanded={open}>
        <span className="dp-head-main">
          <b>{drop.recipient || drop.waybill_number}</b>
          <span className="pp-muted">{drop.address || "No address given"}</span>
        </span>
        {drop.to_collect > 0 && (
          <span className="pp-pill pp-pill-warn">
            Collect {money(drop.to_collect)}
          </span>
        )}
      </button>

      {open && (
        <>
          {/* Tappable, because the next thing a driver does at a gate nobody
              answers is ring the number. */}
          <div className="dp-links">
            {drop.phone && (
              <a className="pp-btn dp-call" href={`tel:${drop.phone.replace(/\s+/g, "")}`}>
                Ring {drop.phone}
              </a>
            )}
            {drop.address && (
              <a className="pp-ghost dp-map"
                 href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(drop.address)}`}
                 target="_blank" rel="noreferrer">
                Find it on a map
              </a>
            )}
          </div>

          {drop.instructions && (
            <p className="pp-muted dp-note">{drop.instructions}</p>
          )}
          {drop.requires_id_check && (
            <div className="pp-alert pp-alert-warn">
              <b>Check their identity document</b>
              <span>
                This one contains a controlled medicine. Write the number down
                before you hand it over.
              </span>
            </div>
          )}
          {oops && <p className="pp-error">{oops}</p>}

          {failing ? (
            <form onSubmit={(e) => {
              e.preventDefault();
              send("failed", { reason });
            }}>
              <label>
                What happened
                <input value={reason} maxLength={200} autoFocus
                       onChange={(e) => setReason(e.target.value)}
                       placeholder="Nobody home, gate locked, wrong address" />
              </label>
              <button disabled={busy || !reason.trim()}>
                {busy ? "Saving…" : "Save and move on"}
              </button>
              <button type="button" className="pp-ghost" disabled={busy}
                      onClick={() => setFailing(false)}>
                Back
              </button>
            </form>
          ) : (
            <form onSubmit={(e) => {
              e.preventDefault();
              send("delivered", {
                received_by: who,
                id_number_seen: idSeen,
                signature,
                cod_instrument: "cod",
              });
            }}>
              <label>
                Who took it
                <input value={who} maxLength={120}
                       onChange={(e) => setWho(e.target.value)}
                       placeholder="Their name" />
              </label>
              {drop.requires_id_check && (
                <label>
                  Identity number
                  <input value={idSeen} maxLength={30} inputMode="text"
                         onChange={(e) => setIdSeen(e.target.value)}
                         placeholder="As it reads on the document" />
                </label>
              )}

              <SignaturePad onChange={setSignature} />

              <button disabled={busy || !who.trim()}>
                {busy ? "Saving…"
                  : drop.to_collect > 0
                    ? `Delivered, ${money(drop.to_collect)} collected`
                    : "Delivered"}
              </button>
              <button type="button" className="pp-ghost" disabled={busy}
                      onClick={() => setFailing(true)}>
                Could not deliver this one
              </button>
            </form>
          )}
        </>
      )}
    </section>
  );
}
