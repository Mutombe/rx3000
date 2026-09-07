/** "A new version is ready" — where a busy counter can see it and ignore it.
 *
 *  WHERE IT IS, AND WHY THERE
 *
 *  In the top bar, immediately left of the branch chip. Three reasons:
 *
 *  It is on every screen, so the offer does not depend on somebody visiting a
 *  settings page they open twice a year.
 *
 *  It is out of the working area. The dispensing strip, the till and the
 *  patient record are where the work is; a banner across the top of those
 *  pushes the work down and gets dismissed on reflex.
 *
 *  It is beside the other two facts about the session — which shop you are in,
 *  and which theme. Those are read between customers, which is exactly when
 *  somebody should decide whether now is a good moment to restart a till.
 *
 *  WHAT IT NEVER DOES
 *
 *  It never installs on its own, never opens a dialog on launch, and never
 *  appears when there is nothing to offer. A till that restarts during a sale
 *  is a worse problem than a till a fortnight out of date.
 */
import { useState } from "react";
import { ArrowClockwise, Check, Warning } from "@phosphor-icons/react";
import { inDesktopApp, useAppUpdate } from "../hooks/useAppUpdate";

export default function UpdateChip() {
  const update = useAppUpdate();
  const [open, setOpen] = useState(false);

  // A browser tab updates by loading the page. Nothing to say here at all.
  if (!inDesktopApp() || update.stage === "none") return null;

  const label =
    update.stage === "available" ? "Update available"
      : update.stage === "fetching" ? "Downloading…"
        : update.stage === "ready" ? "Update ready"
          : update.stage === "installing" ? "Installing…"
            : "Update failed";

  return (
    <>
      <button
        className={`update-chip is-${update.stage}`}
        onClick={() => setOpen(true)}
        title={`RX5000 ${update.version} is available`}
      >
        {update.stage === "failed"
          ? <Warning size={13} weight="fill" aria-hidden="true" />
          : update.stage === "ready"
            ? <Check size={13} weight="bold" aria-hidden="true" />
            : <ArrowClockwise size={13} weight="bold" aria-hidden="true"
                              className={update.stage === "fetching" ? "spin" : undefined} />}
        <span className="update-chip-text">{label}</span>
      </button>

      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>RX5000 {update.version}</h2>

            {update.notes ? (
              <div className="update-notes">{update.notes}</div>
            ) : (
              <p className="muted">
                No notes were published with this release.
              </p>
            )}

            {update.stage === "failed" && (
              <div className="alert error">{update.error}</div>
            )}

            <p className="hint">
              {update.stage === "ready"
                ? "Downloaded and verified. Installing closes the till for a "
                  + "few seconds and opens it again. Finish what is on the "
                  + "screen first."
                : "It downloads in the background. Nothing restarts until you "
                  + "say so."}
            </p>

            <div className="modal-actions">
              <button className="btn" onClick={() => setOpen(false)}>
                {update.stage === "ready" ? "Not now" : "Close"}
              </button>
              {update.stage === "available" && (
                <button className="btn primary"
                        onClick={() => { update.download(); }}>
                  Download it
                </button>
              )}
              {update.stage === "ready" && (
                <button className="btn primary"
                        onClick={() => { update.install(); }}>
                  Install and restart
                </button>
              )}
              {update.stage === "failed" && (
                <button className="btn primary" onClick={() => update.check()}>
                  Try again
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
