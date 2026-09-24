/** The frame every public portal is read inside.
 *
 *  WHOSE SHOPFRONT THIS IS
 *
 *  Three of the four portals put "RX5000" at the top: the software vendor's
 *  name, on a page the pharmacy's own customer is reading. The printed
 *  documents settled that argument a long time ago, and `document.ts` says so
 *  in as many words: the wordmark on a statement is the PHARMACY'S, not ours.
 *  The portals never got the memo, so a patient opening their prescriptions
 *  from an SMS saw a product they have never bought from, and not the shop
 *  they collect at.
 *
 *  So the pharmacy's logo and name are the masthead, its telephone number and
 *  address are the footer, and RX5000 is a line of small print at the bottom
 *  where a supplier's mark belongs.
 *
 *  ONE FRAME, BECAUSE THERE WERE FOUR
 *
 *  Each portal wrote its own header, its own footer, its own spinner and its
 *  own "this link cannot be opened" card. The four had already drifted: two of
 *  them drew the mark as `RX` and one as `℞`, and a fifth copy of the patient's
 *  markup lives in the staff preview. A frame that is written once cannot
 *  disagree with itself.
 */
import { FormEvent, ReactNode, useEffect, useState } from "react";
import { apiBase } from "../api";
import PinInput from "../components/PinInput";
import "./portal.css";

/** What the pharmacy looks like, from `GET /api/portal/brand/{kind}/{token}`.
 *
 *  The same shape the printed letterhead is built from, so a pharmacy that
 *  changes its trading name changes it in one place and both follow.
 */
export interface Brand {
  name: string;
  /** A data URI, or empty where nobody has uploaded one. */
  logo: string;
  phone: string;
  email: string;
  registration_no: string;
  address: string[];
}

/** The pharmacy behind a portal link, fetched once per mount.
 *
 *  Never throws and never blocks: a portal whose branding request fails is a
 *  portal that still has to show somebody their prescriptions. The frame falls
 *  back to its own mark, which is what it drew before any of this.
 */
export function useBrand(kind: string, token?: string): Brand | null {
  const [brand, setBrand] = useState<Brand | null>(null);
  useEffect(() => {
    if (!token) return;
    let live = true;
    fetch(`${apiBase}/api/portal/brand/${kind}/${token}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => { if (live && b && !b.detail) setBrand(b); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [kind, token]);
  return brand;
}

/** The masthead: the pharmacy's own mark, then whatever this page is about. */
export function PortalHead({ brand, title, sub, children }: {
  brand: Brand | null;
  /** The page's own heading, under the pharmacy's name. */
  title?: ReactNode;
  sub?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="pp-head">
      <div className="pp-brandline">
        {brand?.logo
          ? <img className="pp-logo" src={brand.logo} alt={brand.name} />
          : <div className="pp-mark pp-mark-sm" aria-hidden="true">℞</div>}
        <span className="pp-shopname">{brand?.name || "Your pharmacy"}</span>
      </div>
      {title && <h1>{title}</h1>}
      {sub && <p className="pp-muted">{sub}</p>}
      {children}
    </header>
  );
}

/** The footer: how to reach the pharmacy, and who made the software.
 *
 *  The telephone number is a `tel:` link because this is read on a phone and
 *  the next thing somebody does after reading it is ring the shop.
 */
export function PortalFoot({ brand, children }: {
  brand: Brand | null; children?: ReactNode;
}) {
  return (
    <footer className="pp-foot">
      {children && <p className="pp-foot-said">{children}</p>}
      {brand && (brand.phone || brand.address.length > 0) && (
        <p className="pp-foot-shop">
          <b>{brand.name}</b>
          {brand.phone && (
            <>
              {" · "}
              <a className="pp-foot-link" href={`tel:${brand.phone.replace(/\s+/g, "")}`}>
                {brand.phone}
              </a>
            </>
          )}
          {brand.address.length > 0 && <><br />{brand.address.join(", ")}</>}
          {brand.registration_no && <><br />{brand.registration_no}</>}
        </p>
      )}
      <p className="pp-foot-by">Powered by RX5000</p>
    </footer>
  );
}

/** The whole frame: masthead, the page, footer. */
export default function PortalShell({
  brand, title, sub, wide = false, head, foot, children,
}: {
  brand: Brand | null;
  title?: ReactNode;
  sub?: ReactNode;
  /** A portal that needs the roomier column, like the quote form. */
  wide?: boolean;
  /** Extra content inside the masthead, under the heading. */
  head?: ReactNode;
  /** The page's own closing sentence, above the pharmacy's details. */
  foot?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={`pp${wide ? " pp-wide" : ""}`}>
      <PortalHead brand={brand} title={title} sub={sub}>{head}</PortalHead>
      {children}
      <PortalFoot brand={brand}>{foot}</PortalFoot>
    </div>
  );
}

/** The front door: the pharmacy's mark, a greeting, and whatever proves you.
 *
 *  Centred in the screen, like the sign-in the staff use. Each portal used to
 *  put its own door near the top of an empty page, which reads as a form
 *  somebody forgot to finish rather than as the way in.
 */
export function PortalGate({
  brand, title, lead, said, children, action, fine, onSubmit,
}: {
  brand: Brand | null;
  title: ReactNode;
  /** The one fact worth showing before anything has been proved. */
  lead?: ReactNode;
  /** What went wrong on the last attempt, in the server's own words. */
  said?: string;
  /** The fields that prove who this is. */
  children: ReactNode;
  /** The button. Kept below the error, so the reason is read before the retry. */
  action?: ReactNode;
  fine?: ReactNode;
  onSubmit: (e: FormEvent) => void;
}) {
  return (
    <div className="pp pp-gate">
      <form className="pp-card pp-card-centre" onSubmit={onSubmit}>
        {brand?.logo
          ? <img className="pp-logo pp-logo-lg" src={brand.logo} alt={brand.name} />
          : <div className="pp-mark" aria-hidden="true">℞</div>}
        {brand?.name && <p className="pp-gate-shop">{brand.name}</p>}
        <h1>{title}</h1>
        {lead && <p className="pp-lead">{lead}</p>}
        {children}
        {said && <p id="pp-error" className="pp-error" role="alert">{said}</p>}
        {action}
        {fine && <p className="pp-fine">{fine}</p>}
      </form>
      {brand && (brand.phone || brand.address.length > 0) && (
        <PortalFoot brand={brand} />
      )}
    </div>
  );
}

/** The four digits, and the pass they buy.
 *
 *  WHY THE WHOLESALERS GET ONE TOO
 *
 *  The link is signed and expiring, which answers forgery. It does not answer
 *  forwarding, and forwarding is what happens: a quotation request lands in a
 *  shared sales inbox and goes to whoever is free. The code travels in the
 *  body of the message, on its own line, so forwarding the URL opens nothing.
 *
 *  The code itself is posted once. What comes back is a short-lived signed
 *  pass that every later request carries, so the four digits are not in every
 *  proxy log between here and the pharmacy.
 */
export function usePortalPass(kind: string, token: string) {
  // "" means no pass yet; a link with no code on it comes back from the
  // server with an empty pass and `open: true`, and those are different
  // states — one is a locked door, the other is no door.
  const [pass, setPass] = useState("");
  const [open, setOpen] = useState(false);
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);

  async function unlock(code: string) {
    setBusy(true);
    setSaid("");
    try {
      const r = await fetch(`${apiBase}/api/portal/unlock/${kind}/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? "That did not work.");
      setPass(body.pass ?? "");
      setOpen(true);
      return true;
    } catch (e: any) {
      // Shown exactly as the server wrote it. "3 more tries" is the only
      // thing that stops somebody guessing blindly and then ringing to
      // complain the link is broken.
      setSaid(e.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  /** The header every request behind the gate carries. */
  const headers = pass ? { "X-Portal-Pass": pass } : undefined;
  return { pass, open, said, busy, unlock, headers, setSaid };
}

/** The door itself: the shop's mark, four boxes, and one sentence. */
export function PortalDoor({
  brand, title, lead, said, busy, onCode, fine,
}: {
  brand: Brand | null;
  title: ReactNode;
  lead?: ReactNode;
  said?: string;
  busy?: boolean;
  onCode: (code: string) => void;
  fine?: ReactNode;
}) {
  const [code, setCode] = useState("");
  // A refusal clears the boxes, so the next attempt starts from an empty row
  // rather than from a wrong one somebody has to delete first.
  useEffect(() => { if (said) setCode(""); }, [said]);
  return (
    <PortalGate
      brand={brand}
      title={title}
      lead={lead}
      said={said}
      onSubmit={(e) => { e.preventDefault(); if (code.length === 4) onCode(code); }}
      fine={fine ?? ("The pharmacy gave you this code. If you have lost it, "
                     + "ring them and they will give you a new one.")}
    >
      <label className="pp-label" htmlFor="pp-code-1">
        Enter your four-digit code
      </label>
      {/* The same component the till unlocks with: paste, backspace,
          auto-submit and shake-on-refusal are already right there, and a
          second implementation of a PIN box is a second one to get wrong. */}
      <PinInput
        value={code}
        onChange={setCode}
        onComplete={onCode}
        checking={busy}
        invalid={!!said}
        disabled={busy}
      />
    </PortalGate>
  );
}

/** Waiting for the server, on a connection that may be slow. */
export function PortalLoading({ brand }: { brand?: Brand | null }) {
  return (
    <div className="pp pp-centre">
      <div className="pp-card pp-card-centre">
        {brand?.logo
          ? <img className="pp-logo pp-logo-lg" src={brand.logo} alt={brand.name} />
          : <div className="pp-mark" aria-hidden="true">℞</div>}
        <div className="pp-spinner" aria-hidden="true" />
        <p className="pp-muted">Fetching this from the pharmacy…</p>
      </div>
    </div>
  );
}

/** A link that has expired, been replaced, or was never valid.
 *
 *  One card, one wording. There were three of these and they had already
 *  drifted apart, which is how a patient and a wholesaler get told two
 *  different things about the same kind of dead link.
 */
export function PortalGone({ brand, said }: { brand?: Brand | null; said?: string }) {
  return (
    <div className="pp pp-centre">
      <div className="pp-card pp-card-centre">
        {brand?.logo
          ? <img className="pp-logo pp-logo-lg" src={brand.logo} alt={brand.name} />
          : <div className="pp-mark" aria-hidden="true">℞</div>}
        <h1 className="pp-gone-title">This link has expired</h1>
        <p className="pp-muted">
          {said || "Links are time-limited on purpose. Ring the pharmacy and "
            + "they will send you a fresh one."}
        </p>
        {brand?.phone && (
          <a className="pp-btn" href={`tel:${brand.phone.replace(/\s+/g, "")}`}>
            Ring {brand.name}
          </a>
        )}
      </div>
    </div>
  );
}
