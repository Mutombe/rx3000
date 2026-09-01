/** The password prompt for actions that need one.
 *
 *  Two different things happen behind this one dialog, and conflating them is
 *  the usual mistake:
 *
 *    re-authentication   "prove you are still you" — the till has been left
 *                        unattended and the action is destructive
 *    supervisor override "get someone senior to approve" — the cashier cannot
 *                        discount, so the manager walks over and types their
 *                        own password on the cashier's till
 *
 *  The second is what actually happens at a counter, so where the action
 *  forbids self-approval the dialog asks *who* is approving before it asks for
 *  a password. A dialog that only ever asked "your password" would force the
 *  manager to log the cashier out, which in practice means the manager's
 *  password ends up known to the whole shop.
 *
 *  The server is the authority on all of this. This component asks it what the
 *  action requires rather than hard-coding it, so protecting a new action never
 *  means editing the UI.
 */
import { useEffect, useState } from "react";
import { Warning } from "@phosphor-icons/react";
import { api } from "../api";
import BusyButton from "./BusyButton";
import PinInput from "./PinInput";

/** Kept beside the dialog that reads it, so "is the PIN finished" is one fact
 *  rather than a 4 typed in two files that can drift apart. */
const PIN_LENGTH = 4;

export interface StepUpAction {
  key: string;
  name: string;
  why: string;
  approvers: string[];
  self_approval: boolean;
  valid_seconds: number;
}

interface Props {
  /** e.g. "sale.void" */
  action: string;
  /** What this is for — shown to the approver and kept in the audit log. */
  context?: string;
  /** Called with a single-use token once authority is granted. */
  onGranted: (token: string) => void;
  onCancel: () => void;
}

export default function StepUp({ action, context = "", onGranted, onCancel }: Props) {
  const [spec, setSpec] = useState<StepUpAction | null>(null);
  const [approver, setApprover] = useState("");
  const [password, setPassword] = useState("");
  /* PIN first, password as the way out.
     This prompt interrupts a transaction with a patient at the counter. A
     password typed there is a password read over a shoulder, and one long
     enough to be worth having is long enough that people start picking bad
     ones. Four digits, rate limited and locked after five failures, is the
     trade this particular prompt is for. Anyone without a PIN set, and anyone
     who would rather, still uses a password. */
  const [pin, setPin] = useState("");
  const [usePassword, setUsePassword] = useState(false);
  const [pinRefused, setPinRefused] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const needsSecondPerson = spec && !spec.self_approval;

  useEffect(() => {
    api
      .get<StepUpAction[]>("/api/step-up/actions")
      .then((all) => setSpec(all.find((a) => a.key === action) || null))
      .catch((e) => setError(e.message));
  }, [action]);

  /** Whether there is enough here to send.
   *
   *  This used to be `!password` regardless of which credential was on screen,
   *  so in PIN mode — the default, and the one this dialog was designed around
   *  — the Authorise button was disabled no matter how many digits were typed.
   *  Nothing was wired to submit on the fourth digit either, so a PIN could not
   *  authorise anything at all.
   */
  const complete = usePassword
    ? password.length > 0
    : pin.length === PIN_LENGTH;
  const ready = complete && (!needsSecondPerson || !!approver.trim());

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ token: string }>("/api/step-up", {
        action,
        ...(usePassword ? { password } : { pin }),
        approver: approver.trim(),
        context,
      });
      onGranted(res.token);
    } catch (err: any) {
      // The server's refusal is the useful message — "not permitted to approve",
      setPinRefused(!usePassword);
      // "needs a second person", "that password was not accepted", so it is
      // shown as written rather than replaced with something generic.
      setError(err.message);
      setPassword("");
      // The boxes shake, then empty themselves. Retyping over a wrong PIN one
      // digit at a time is how the second attempt becomes a third.
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>{spec ? spec.name : "Authorisation required"}</h2>

        {spec && <p className="muted">{spec.why}</p>}

        {needsSecondPerson ? (
          <p className="alert warn">
            This needs a second person. Ask{" "}
            {/* "an admin", not "a admin". It is the one line somebody reads
                with a customer waiting. */}
            {"aeiou".includes(spec!.approvers.join(" or ")[0]?.toLowerCase()) ? "an" : "a"}{" "}
            {spec!.approvers.join(" or ")} to enter
            their own username and password, not yours.
          </p>
        ) : (
          <p className="muted">
            {usePassword
              ? "Re-enter your password to confirm."
              : "Enter your till PIN to confirm."}
          </p>
        )}

        {/* A refusal is the most important thing on the dialog the moment it
            happens: it says whether to try again, fetch a manager, or stop.
            role="alert" so it is announced rather than only drawn. */}
        {error && (
          <div className="alert error su-error" role="alert">
            <Warning size={16} weight="fill" />
            <span>{error}</span>
          </div>
        )}

        {needsSecondPerson && (
          <label>
            Approver's username
            <input
              value={approver}
              autoFocus
              autoComplete="off"
              onChange={(e) => setApprover(e.target.value)}
              placeholder={spec!.approvers[0]}
            />
          </label>
        )}

        {usePassword ? (
          <label>
            Password
            <input
              type="password"
              value={password}
              autoFocus={!needsSecondPerson}
              autoComplete="off"
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
        ) : (
          <div className="su-pin">
            <span className="su-pin-label">
              {needsSecondPerson ? "Approver's PIN" : "Your PIN"}
            </span>
            <PinInput
              length={PIN_LENGTH}
              value={pin}
              onChange={(v) => { setPin(v); setPinRefused(false); }}
              // Four keystrokes and nothing else, which is what the component
              // was built for and what nobody had connected. Held back while a
              // second person is required: the approver's username has to be
              // filled first, and submitting without it only earns a refusal.
              onComplete={() => { if (!needsSecondPerson || approver.trim()) submit(); }}
              autoFocus={!needsSecondPerson}
              invalid={pinRefused}
              disabled={busy}
            />
          </div>
        )}

        <button
          type="button"
          className="ghost small su-swap"
          onClick={() => { setUsePassword((p) => !p); setPin(""); setPassword(""); }}
        >
          {usePassword ? "Use a PIN instead" : "Use a password instead"}
        </button>

        {spec && (
          <p className="muted small">
            Valid for {Math.round(spec.valid_seconds / 60)} minute
            {spec.valid_seconds >= 120 ? "s" : ""}, for this one action. Every attempt
            is recorded, including refusals.
          </p>
        )}

        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onCancel}>
            Cancel
          </button>
          <BusyButton
            type="submit"
            className="btn primary"
            disabled={!ready}
            busyLabel="Checking…"
            onClick={submit}
          >
            Authorise
          </BusyButton>
        </div>
      </form>
    </div>
  );
}

/** What `guarded` resolves to when the person closed the dialog instead of
 *  authorising. A distinct value rather than `undefined`, because `undefined` is
 *  also what a 204 returns, so a caller could not tell "nothing to send back"
 *  from "nobody approved this", and would report a cancelled action as done.
 */
export const CANCELLED = Symbol("step-up cancelled");

/** Run a request that needs authority, prompting for it only if the server asks.
 *
 *  Deliberately optimistic: it tries without a token first. Most protected
 *  actions are attempted by someone who turns out to be allowed, and a dialog
 *  shown before it is needed trains people to type passwords on reflex — which
 *  is the habit the prompt exists to prevent.
 *
 *  Callers must check the result against CANCELLED before announcing success.
 *  Cancelling is not an error, nothing went wrong and nothing happened, so it
 *  is not thrown; an error toast reading "cancelled" describes a fault that does
 *  not exist.
 */
export function useStepUp() {
  const [pending, setPending] = useState<{
    action: string;
    context: string;
    run: (token: string) => void;
    cancel: () => void;
  } | null>(null);

  async function guarded<T>(
    action: string,
    attempt: (token?: string) => Promise<T>,
    context = "",
  ): Promise<T | typeof CANCELLED> {
    try {
      return await attempt();
    } catch (err: any) {
      // 428 is the server saying 'signed in, but this needs more authority'.
      if (err?.status !== 428) throw err;
      return new Promise<T | typeof CANCELLED>((resolve, reject) => {
        setPending({
          action,
          context,
          run: async (token: string) => {
            setPending(null);
            // The retry can fail on its own account — a wrong password is
            // handled inside the dialog, but the authorised call can still hit
            // a closed period or a stock rule. Rejecting hands that to the
            // caller's catch; resolving would have swallowed it and left the
            // screen claiming the work was done.
            try {
              resolve(await attempt(token));
            } catch (retryErr) {
              reject(retryErr);
            }
          },
          cancel: () => resolve(CANCELLED),
        });
      });
    }
  }

  const prompt = pending ? (
    <StepUp
      action={pending.action}
      context={pending.context}
      onGranted={pending.run}
      // Settles the promise. Without this the awaiting caller hangs forever, so
      // anything it set before calling, a busy flag, a disabled button, stays
      // set and the screen looks stuck mid-save.
      onCancel={() => { const c = pending.cancel; setPending(null); c(); }}
    />
  ) : null;

  return { guarded, prompt };
}
