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
import { Block } from "../components/Skeleton";
import { PortalApp, PortalBy, PortalDoor, PortalGone,
  PortalMark, PortalNav, PortalNone, useBrand, usePortalPass } from "./PortalShell";
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
  const [tab, setTab] = useState<"stop" | "round" | "shop">("stop");

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
  /* THE ROUND ARRIVES INTO A SCREEN, NOT INSTEAD OF ONE.
   *
   * This returned a centred spinner reading "Fetching this from the
   * pharmacy...", so a driver who had just typed their code correctly was
   * shown a card with no bar, no tabs and nothing they could act on, and then
   * a different screen. By this point the shell is entirely known: the
   * pharmacy's mark, the driver's own top bar and the three tabs are not
   * fetched, and on a phone at the roadside the frame arriving first is the
   * difference between a screen that is loading and one that is broken.
   *
   * Only the door itself waits, at the size a door card takes. */
  if (!run) {
    return (
      <PortalApp
        bar={
          <>
            <PortalMark brand={brand} small />
            <span className="pp-appbar-said">
              <b className="pp-appbar-shop">{brand?.name || "Your round"}</b>
              <span className="pp-appbar-who">Fetching your round</span>
            </span>
          </>
        }
        nav={
          <PortalNav
            tabs={[
              { key: "stop" as const, label: "This stop", icon: <IconDoor /> },
              { key: "round" as const, label: "The round", icon: <IconList /> },
              { key: "shop" as const, label: "Pharmacy", icon: <IconShop /> },
            ]}
            tab={tab}
            setTab={setTab}
          />
        }
      >
        <section className="pp-card dp-drop" aria-busy="true">
          <div className="dp-where">
            <Block w="6ch" h={12} />
            <Block w="80%" h={26} />
            <Block w="55%" h={14} />
          </div>
        </section>
      </PortalApp>
    );
  }

  /* The stop being worked on, and the rest of the round. A driver is standing
     at one door: that door is the screen, and the round is a tap away. The
     list used to be the screen, with every stop's card stacked down 1,751px of
     page and the two buttons that close a delivery at the bottom of the open
     one — under the signature pad, which is the tallest thing on it. */
  const stop = run.drops.find((d) => d.id === open) ?? run.drops[0] ?? null;
  const done = run.done_today;
  const left = run.drops.length;

  const tabs = [
    { key: "stop" as const, label: "This stop", icon: <IconDoor />,
      badge: stop && stop.to_collect > 0 ? undefined : undefined },
    { key: "round" as const, label: "The round", icon: <IconList />,
      badge: left },
    { key: "shop" as const, label: "Pharmacy", icon: <IconShop /> },
  ];

  return (
    <PortalApp
      bar={
        <>
          <PortalMark brand={brand} small />
          <span className="pp-appbar-said">
            <b className="pp-appbar-shop">{run.driver}</b>
            <span className="pp-appbar-who">{run.says}</span>
          </span>
          {/* What they are carrying, on the bar rather than on a card that
              scrolls away. It is the one number the shop and the driver argue
              about at the end of a round, and a driver who can see it coming
              can head back before the limit. */}
          {run.holding > 0 && (
            <span className={`dp-purse-chip${
              run.cod_limit > 0 && run.holding > run.cod_limit ? " over" : ""}`}>
              {money(run.holding)}
            </span>
          )}
        </>
      }
      nav={<PortalNav tabs={tabs} tab={tab} setTab={setTab} />}
    >
      {error && <p className="pp-error">{error}</p>}

      {tab === "stop" && (
        !stop ? (
          <section className="pp-card">
            <PortalNone
              mark={<IconDoor />}
              said="Nothing out with you"
              next="When the pharmacy sends something out with you it appears
                    here, with the address and who to hand it to."
            />
          </section>
        ) : (
          <DropCard
            key={stop.id}
            token={token}
            drop={stop}
            headers={gate.headers}
            position={`${done + 1} of ${done + left}`}
            onDone={() => { setOpen(null); load(); }}
          />
        )
      )}

      {tab === "round" && (
        <>
          <section className="pp-card pp-sec">
            <h2>
              Still to go
              {left > 0 && <span className="pp-sec-n">{left}</span>}
            </h2>
            <div className="pp-sec-body">
              {left === 0 ? (
                <PortalNone
                  mark={<IconList />}
                  said={done > 0 ? "That is the round" : "Nothing out with you"}
                  next={done > 0
                    ? `${done} delivered today. Take the money back to the shop.`
                    : "The pharmacy will send you a message when there is."}
                />
              ) : run.drops.map((d, i) => (
                <button
                  key={d.id}
                  type="button"
                  className={`dp-stop${d.id === stop?.id ? " on" : ""}`}
                  onClick={() => { setOpen(d.id); setTab("stop"); }}
                >
                  <span className="dp-stop-n">{done + i + 1}</span>
                  <span className="dp-stop-said">
                    <b>{d.recipient || d.waybill_number}</b>
                    <span className="pp-muted">{d.address || "No address given"}</span>
                  </span>
                  {d.to_collect > 0 && (
                    <span className="pp-pill pp-pill-warn">{money(d.to_collect)}</span>
                  )}
                </button>
              ))}
            </div>
          </section>

          {done > 0 && (
            <section className="pp-card pp-sec">
              <h2>
                Done today
                <span className="pp-sec-n">{done}</span>
              </h2>
              <div className="pp-sec-body">
                <p className="pp-muted" style={{ marginTop: 0 }}>
                  Each one is signed for at the door and stamped with the time.
                </p>
              </div>
            </section>
          )}
        </>
      )}

      {tab === "shop" && (
        <>
          <section className="pp-card pp-shopcard">
            <PortalMark brand={brand} />
            <h1 className="pp-shopname-lg">{brand?.name || "The pharmacy"}</h1>
            {brand && brand.address.length > 0 && (
              <p className="pp-shopline">{brand.address.join(", ")}</p>
            )}
          </section>
          <div className="pp-acts">
            {brand?.phone && (
              <a className="pp-act" href={`tel:${brand.phone.replace(/\s+/g, "")}`}>
                <IconPhone />
                <span>
                  Ring the pharmacy
                  <span className="pp-act-said">{brand.phone}</span>
                </span>
                <span className="pp-act-go" aria-hidden="true"><IconGo /></span>
              </a>
            )}
            {brand && brand.address.length > 0 && (
              <a
                className="pp-act"
                target="_blank"
                rel="noreferrer"
                href={`https://www.google.com/maps/search/?api=1&query=${
                  encodeURIComponent([brand.name, ...brand.address].join(", "))}`}
              >
                <IconPin />
                <span>
                  Back to the shop
                  <span className="pp-act-said">{brand.address.join(", ")}</span>
                </span>
                <span className="pp-act-go" aria-hidden="true"><IconGo /></span>
              </a>
            )}
          </div>
          <p className="pp-shopline" style={{ marginTop: "var(--pp-5)",
                                              textAlign: "center" }}>
            Every delivery you close here is signed for at the door and stamped
            with the time. Ring the pharmacy if anything looks wrong.
          </p>
          <PortalBy />
        </>
      )}
    </PortalApp>
  );
}

/** The one door they are standing at.
 *
 *  It used to be a card in a list, collapsed behind a header somebody had to
 *  tap, with every other stop stacked under it. A driver is at ONE door: that
 *  door is the screen. The round is its own tab, and choosing a stop there
 *  brings it here.
 */
function DropCard({ token, drop, position, onDone, headers }: {
  token: string;
  drop: Drop;
  /** "3 of 6" — where this door sits in the afternoon. */
  position: string;
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
    <section className="pp-card dp-drop">
      {/* The address, set as the largest thing on the screen, because finding
          the door is the job. The name is who to ask for once they are there. */}
      <div className="dp-where">
        <span className="dp-where-n">{position}</span>
        <b className="dp-addr">{drop.address || "No address given"}</b>
        <span className="dp-who">
          {drop.recipient || drop.waybill_number}
        </span>
        {drop.to_collect > 0 && (
          <span className="dp-collect">
            Collect {money(drop.to_collect)}
          </span>
        )}
      </div>

      {(
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
              <div className="dp-decide">
                <button disabled={busy || !reason.trim()}>
                  {busy ? "Saving…" : "Save and move on"}
                </button>
                <button type="button" className="pp-ghost" disabled={busy}
                        onClick={() => setFailing(false)}>
                  Back
                </button>
              </div>
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

              {/* THE TWO DECISIONS DO NOT SCROLL AWAY.
                  Measured at a door on a 390x844 phone: "Delivered" sat at
                  924px and "Could not deliver" at 974px — both off the bottom
                  of the screen, under the signature pad, which is the tallest
                  thing on the form. A driver holding a bag in one hand had to
                  scroll past a signature box to say what happened. They stay
                  on the glass now, above the navigation. */}
              <div className="dp-decide">
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
              </div>
            </form>
          )}
        </>
      )}
    </section>
  );
}

/* The marks. Drawn here rather than imported, for the same reason the
   patient's are: a driver's phone should not download the staff application's
   icon set to close a delivery. */
const svg = {
  width: 24, height: 24, viewBox: "0 0 24 24", fill: "none",
  stroke: "currentColor", strokeWidth: 1.8,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
};
function IconDoor() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M5 21V4a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v17" />
      <path d="M3 21h18" /><circle cx="13" cy="12" r="1" />
    </svg>
  );
}
function IconList() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M8 6h12M8 12h12M8 18h12" />
      <circle cx="4" cy="6" r="1" /><circle cx="4" cy="12" r="1" />
      <circle cx="4" cy="18" r="1" />
    </svg>
  );
}
function IconShop() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M4 9h16v11H4z" /><path d="M3 9l1.6-4.5h14.8L21 9" />
      <path d="M10 20v-5h4v5" />
    </svg>
  );
}
function IconPhone() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M6 3h3l2 5-2.5 1.5a12 12 0 0 0 6 6L16 13l5 2v3a2 2 0 0 1-2.2 2A17 17 0 0 1 4 5.2 2 2 0 0 1 6 3z" />
    </svg>
  );
}
function IconPin() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  );
}
function IconGo() {
  return (
    <svg {...svg} width={18} height={18} aria-hidden="true">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}
