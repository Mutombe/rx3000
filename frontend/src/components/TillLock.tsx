/** The screen lock for a shared till.
 *
 *  A pharmacy till is signed in when the shop opens and used by whoever is
 *  standing at it. That is not a policy failure, it is how the counter works,
 *  and software that pretends otherwise gets switched off: log a pharmacist out
 *  between customers and they lose the basket and the open script, so the
 *  timeout gets disabled and the machine then sits signed in all day with every
 *  action attributed to whoever opened the shop.
 *
 *  So this locks rather than logs out. The session, the basket and the open
 *  script all survive; the only question asked is who is back at the keyboard.
 *  Someone else can take the till over by naming themselves, and what happens
 *  next is recorded against them.
 *
 *  Deliberately not a security boundary. It stops the person behind you in the
 *  queue reading a patient record over the counter, and it makes the audit trail
 *  mean something. It does not stop somebody who knows a colleague's PIN, and
 *  the log exists to make that visible rather than impossible.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText } from "../api";
import PinInput from "./PinInput";
import type { User } from "../types";
import { lockGate } from "../lockGate";

/** Long enough not to interrupt a slow transaction, short enough that a till
 *  left alone while somebody walks to the dispensary is not readable. */
const DEFAULT_IDLE_MS = 5 * 60 * 1000;

/** `?lockAfter=2000` shortens the wait.
 *
 *  For showing somebody the lock without asking them to sit still for five
 *  minutes, and for testing it at all. It can only ever make the till lock
 *  sooner, so there is nothing to gain by setting it. */
function idleMs(): number {
  const asked = Number(new URLSearchParams(window.location.search).get("lockAfter"));
  return Number.isFinite(asked) && asked >= 500 ? asked : DEFAULT_IDLE_MS;
}
const ACTIVITY = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

export default function TillLock({
  user, onActorChange,
}: {
  user: User | null;
  /** Someone else took the till. The page records what follows against them. */
  onActorChange?: (u: User) => void;
}) {
  /* Locked is held in the gate, not here, because the API layer needs to know
     it too: a write attempted from anywhere brings this prompt back. */
  const [, force] = useState(0);
  useEffect(() => {
    // Braced so the effect returns the unsubscribe function rather than the
    // Set#delete boolean an arrow body would hand back.
    const off = lockGate.subscribe(() => force((n) => n + 1));
    return () => { off(); };
  }, []);
  const locked = lockGate.isLocked();
  const prompting = lockGate.isPrompting();
  const [pin, setPin] = useState("");
  const [takingOver, setTakingOver] = useState(false);
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const timer = useRef(0);

  // Only lock a till whose user can unlock it. Somebody with no PIN set would be
  // locked out of their own session with no way back except signing in again,
  // which is the very thing this exists to avoid.
  useEffect(() => {
    let live = true;
    api.get<{ pin_set: boolean }>("/api/auth/pin")
      .then((s) => { if (live) setEnabled(s.pin_set); })
      .catch(() => { if (live) setEnabled(false); });
    return () => { live = false; };
  }, [user?.id]);

  const arm = useCallback(() => {
    window.clearTimeout(timer.current);
    if (!enabled || locked) return;
    timer.current = window.setTimeout(() => lockGate.lock(), idleMs());
  }, [enabled, locked]);

  useEffect(() => {
    if (!enabled) return;
    arm();
    for (const e of ACTIVITY) window.addEventListener(e, arm, { passive: true });
    return () => {
      window.clearTimeout(timer.current);
      for (const e of ACTIVITY) window.removeEventListener(e, arm);
    };
  }, [arm, enabled]);

  async function unlock(code: string) {
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ user: User; took_over: boolean }>(
        "/api/auth/unlock",
        { pin: code, username: takingOver ? username.trim() : "" },
      );
      lockGate.unlock();
      setPin("");
      setTakingOver(false);
      setUsername("");
      if (res.took_over) onActorChange?.(res.user);
    } catch (e) {
      setError(errorText(e, "That PIN was not accepted."));
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  // Dismissed, but still locked: a quiet banner rather than nothing, so the
  // state is never a surprise when the next action stops.
  if (locked && !prompting) {
    return (
      <button
        type="button"
        className="lock-bar"
        onClick={() => lockGate.prompt()}
      >
        <span className="lock-dot" aria-hidden="true" />
        Till locked. You can read, but anything that changes data will ask for a PIN.
        <b>Unlock</b>
      </button>
    );
  }

  if (!prompting) return null;

  return (
    // Dismissible, but the till stays locked underneath: see "Not now" below.
    <div className="lock" role="dialog" aria-modal="true" aria-label="Till locked">
      <div className="lock-card">
        <div className="lock-head">
          <span className="lock-dot" aria-hidden="true" />
          <div>
            <h2>Till locked</h2>
            <p className="muted">
              Nothing has been lost. The basket and any open script are still here.
            </p>
          </div>
        </div>

        {takingOver ? (
          <label className="lock-field">
            Who is taking over
            <input
              value={username}
              autoFocus
              autoComplete="off"
              placeholder="username"
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
        ) : (
          <p className="lock-who">
            <b>{user?.full_name ?? "Signed in"}</b>
            <span className="muted">{user?.role}</span>
          </p>
        )}

        {error && <div className="alert error">{error}</div>}

        <PinInput
          value={pin}
          onChange={(v) => { setPin(v); setError(""); }}
          onComplete={unlock}
          invalid={!!error}
          disabled={busy}
        />

        <div className="lock-actions">
          <button
            type="button"
            className="ghost small"
            onClick={() => { setTakingOver((t) => !t); setPin(""); setError(""); }}
          >
            {takingOver ? "It is still me" : "Someone else is taking over"}
          </button>
          {/* A way out. The till stays locked and reading continues; the next
              thing that would change data brings this back. Anything that was
              already waiting on the gate is let go rather than left pending. */}
          <button
            type="button"
            className="ghost small"
            onClick={() => { lockGate.abandon(); lockGate.dismiss(); setPin(""); setError(""); }}
          >
            Not now
          </button>
        </div>

        <p className="muted small lock-note">
          {/* Said plainly, because an operator who does not know this will fight
              the lock rather than use it. */}
          The till locks after five quiet minutes. Unlocking does not start a new
          session, and whatever happens next is recorded against whoever unlocked it.
        </p>
      </div>
    </div>
  );
}
