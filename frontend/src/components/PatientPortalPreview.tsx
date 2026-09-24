/** The patient's portal, seen from behind the counter.
 *
 *  "It does not show my tablets" cannot be answered from a description, and the
 *  alternative — asking the patient to read their four-digit code down the
 *  telephone — teaches them to give it away, which is the one habit the code
 *  exists to prevent.
 *
 *  So this is their record, read through a staff session that is already
 *  authenticated and already audited. It is not a live portal session and does
 *  not pretend to be one: no token is minted, nothing is signed in as them, and
 *  the banner says so. The distinction matters because a member of staff who
 *  believes they are *inside* the patient's session will believe anything they
 *  change here reaches the patient, and nothing here changes anything.
 */
import { useEffect, useState } from "react";
import { X } from "@phosphor-icons/react";
import { letterhead } from "../letterhead";
import { PortalFoot, PortalHead, type Brand } from "../portal/PortalShell";
// The portal's own stylesheet, so the preview is the patient's page rather
// than its markup with none of its rules. Without this the phone frame held
// raw browser defaults — bold runs, no cards, no spacing — which is not what
// the patient sees and is worse than showing nothing. Every rule in it is
// scoped under `.pp`, so loading it here changes nothing else on the screen.
import "../portal/portal.css";

const money = (n: number) =>
  n.toLocaleString(undefined, { style: "currency", currency: "USD" });
const day = (s: string | null) =>
  s ? new Date(s).toLocaleDateString(undefined,
    { day: "numeric", month: "short", year: "numeric" }) : "";

export default function PatientPortalPreview(
  { record, onClose }: { record: any; onClose: () => void },
) {
  // The pharmacy's own particulars, from the same place the printed letterhead
  // takes them. The preview used to draw a generic mark and no shop name, so
  // staff were shown a page the patient does not get.
  const [brand, setBrand] = useState<Brand | null>(null);
  useEffect(() => {
    letterhead().then((l) => setBrand({
      name: l.display_name || l.legal_name || "",
      logo: l.logo || "",
      phone: l.phone || "",
      email: l.email || "",
      registration_no: l.registration_no || "",
      address: l.address || [],
    }));
  }, []);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide preview-shell" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <div>
            <h2>What {record.first_name} sees</h2>
            <span className="muted small">{record.note}</span>
          </div>
          <button className="btn ghost sm" onClick={onClose}>
            <X size={14} weight="bold" />
          </button>
        </div>

        {record.code && (
          <p className="hint">
            Their code is <b className="mono">{record.code}</b>. Read it to them
            rather than asking them to read it to you.
          </p>
        )}

        {/* Rendered in the portal's own stylesheet inside a phone-width frame,
            so what staff see is what the patient sees rather than a staff-styled
            approximation of it. An approximation is how "it looks fine here"
            becomes an unresolvable argument. */}
        <div className="preview-phone">
          <div className="pp">
            {/* The portal's own masthead and footer, imported rather than
                copied. This was a fifth hand-written copy of the patient's
                markup and it had already drifted from the other four. */}
            <PortalHead brand={brand} title={record.first_name}
                        sub={record.medical_aid} />

            {record.allergies && (
              <div className="pp-alert pp-alert-bad">
                <b>Allergic to {record.allergies}</b>
                <span>Tell any pharmacist or doctor who treats you.</span>
              </div>
            )}

            <section className="pp-card">
              <h2>Ready to collect</h2>
              {!record.waiting?.length ? (
                <p className="pp-muted">Nothing is waiting for you.</p>
              ) : record.waiting.map((w: any, i: number) => (
                <div key={i} className="pp-row">
                  <div>
                    <b>{w.product}</b>
                    <span className="pp-muted">
                      {w.quantity} · since {day(w.since)}
                    </span>
                  </div>
                  <span className="pp-pill pp-pill-ok">Ready</span>
                </div>
              ))}
            </section>

            <section className="pp-card">
              <h2>Due next</h2>
              {!record.due?.length ? (
                <p className="pp-muted">Nothing is due.</p>
              ) : record.due.slice(0, 6).map((d: any, i: number) => (
                <div key={i} className="pp-row">
                  <div>
                    <b>{d.product}</b>
                    <span className="pp-muted">
                      {d.overdue ? `Was due ${Math.abs(d.days)} days ago`
                        : d.days === 0 ? "Due today" : `Due in ${d.days} days`}
                    </span>
                  </div>
                  <span className={`pp-pill ${d.overdue ? "pp-pill-bad" : ""}`}>
                    {day(d.on)}
                  </span>
                </div>
              ))}
            </section>

            {record.owed > 0 && (
              <section className="pp-card pp-split">
                <div>
                  <span className="pp-muted">Outstanding</span>
                  <b className="pp-big">{money(record.owed)}</b>
                </div>
              </section>
            )}

            <PortalFoot brand={brand} />
          </div>
        </div>
      </div>
    </div>
  );
}
