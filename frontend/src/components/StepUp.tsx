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
 *
 *  It also sets a code, in place, for somebody who has not got one.
 *
 *  That is not a settings screen wedged into a dialog: it is the only way the
 *  moment works. A pharmacist walks to a cashier's till to approve an override,
 *  the prompt asks for their code, and they have never set one. Without this
 *  their route is to log the cashier out, sign in, find settings, set a code,
 *  sign out, sign the cashier back in — and by then the transaction is gone and
 *  the patient has been standing at a counter watching it happen. So the thing
 *  they are missing is made here, and the dialog they were in is still open
 *  behind it with everything they had typed.
 */
import { useEffect, useRef, useState } from "react";
import { Key, Warning } from "@phosphor-icons/react";
import { api } from "../api";
import { useSession } from "../session";
import BusyButton from "./BusyButton";
import PinInput from "./PinInput";
import { toast } from "./Toast";

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
  /** What a demo visitor needs to get past this prompt.
   *
   *  A demo account is issued a session rather than credentials, so there was
   *  nothing a visitor could type here and every protected action dead-ended:
   *  the dialog asked them to re-enter a password that had never existed. The
   *  demonstration tenant now has a code, and a pharmacist to call over for
   *  the three actions nobody may approve alone. Saying both here is the
   *  point — a code the visitor has to guess is the same dead end wearing a
   *  different hat.
   *
   *  Empty for every real session, because the server answers nothing to one. */
  const [demo, setDemo] = useState<{ pin: string; approver: string;
                                     approver_name: string } | null>(null);
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
  /** Sent for checking, so the dialog is off the screen. It stays mounted, and
   *  keeps everything typed into it, because a refusal has to be able to put it
   *  back exactly as it was rather than as a fresh prompt. */
  const [sent, setSent] = useState(false);
  const needsSecondPerson = spec && !spec.self_approval;

  const { me } = useSession();

  useEffect(() => {
    if (!me?.is_demo) return;
    let live = true;
    api.get<{ pin: string; approver: string; approver_name: string }>(
      "/api/auth/demo/state")
      .then((said) => { if (live && said.pin) setDemo(said); })
      .catch(() => { /* a hint that will not load must not block the prompt */ });
    return () => { live = false; };
  }, [me?.is_demo]);

  // The colleague to call over, filled in rather than guessed at. A visitor
  // cannot know the name of a member of staff in a pharmacy they have never
  // seen, and an empty required field is the dead end again.
  useEffect(() => {
    if (demo?.approver && needsSecondPerson && !approver) setApprover(demo.approver);
  }, [demo, needsSecondPerson, approver]);

  /* Making a code, here, without leaving. Everything above stays mounted while
     this is open, so the approver's username, the action and the context are
     still there when it closes — which is the whole point of doing it here. */
  const [making, setMaking] = useState(false);
  const [newPin, setNewPin] = useState("");
  const [againPin, setAgainPin] = useState("");
  const [madeFor, setMadeFor] = useState("");
  const pinBoxes = useRef<HTMLDivElement | null>(null);

  /** Whose code is being set: the approver where a second person is required,
   *  otherwise whoever is signed in. Editable, because the person standing at
   *  the till may not be either. */
  const owner = (needsSecondPerson ? approver.trim() : "") || me?.username || "";
  const [makeAs, setMakeAs] = useState("");
  /* The server's own words for "this person has no code", so the offer to make
     one appears exactly when it is the answer rather than on every refusal. */
  const noCodeYet = /no pin is set/i.test(error);
  /** Whether the person signed in here has a code of their own yet.
   *
   *  Asked about the CURRENT user only, never about a username somebody types:
   *  an endpoint that says whether an arbitrary account has a code is an
   *  endpoint that says which accounts exist. For an approver walking up to
   *  somebody else's till, the offer still waits for the server to say there is
   *  no code, which it only does once a real attempt has been made. */
  const [iHaveCode, setIHaveCode] = useState<boolean | null>(null);
  useEffect(() => {
    api.get<{ pin_set: boolean }>("/api/auth/pin")
      .then((s) => setIHaveCode(!!s.pin_set))
      .catch(() => setIHaveCode(null));
  }, []);
  const offerToMake = noCodeYet || (!needsSecondPerson && iHaveCode === false);

  function startMaking() {
    setMakeAs(owner);
    setPassword("");
    setNewPin("");
    setAgainPin("");
    setError("");
    setMaking(true);
  }

  async function makeTheCode(e?: React.FormEvent) {
    e?.preventDefault();
    if (busy) return;
    if (newPin.length !== PIN_LENGTH || againPin.length !== PIN_LENGTH) return;
    if (newPin !== againPin) {
      // Said before the server is asked. A mismatch is not a refusal and should
      // not read like one.
      setError("Those two codes are not the same.");
      setAgainPin("");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const said = await api.post<{ full_name?: string; username?: string }>(
        "/api/auth/pin",
        { pin: newPin, password, username: makeAs.trim() },
      );
      // Straight back to what they were doing, with the code they have just
      // chosen ready to type. Nothing that was filled in has moved.
      setMaking(false);
      setMadeFor(said?.full_name || said?.username || makeAs.trim());
      setPassword("");
      setNewPin("");
      setAgainPin("");
      setPin("");
      setUsePassword(false);
      if (needsSecondPerson && said?.username) setApprover(said.username);
      window.setTimeout(
        () => pinBoxes.current?.querySelector("input")?.focus(), 60);
    } catch (err: any) {
      setError(err.message);
      setNewPin("");
      setAgainPin("");
    } finally {
      setBusy(false);
    }
  }

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

  /** `typed` is the PIN as the boxes have it *now*.
   *
   *  The fourth digit fires this from inside the box's own change handler, one
   *  render before `pin` catches up — so reading state here meant `complete`
   *  was false on the only keystroke that matters, and the dialog sat there
   *  with four dots in it doing nothing. Passed in rather than read.
   */
  async function submit(e?: React.FormEvent, typed?: string) {
    e?.preventDefault();
    const credential = usePassword ? password : (typed ?? pin);
    const enough = usePassword
      ? credential.length > 0
      : credential.length === PIN_LENGTH;
    if (!enough || (needsSecondPerson && !approver.trim()) || busy) return;
    setBusy(true);
    setError("");

    // THE DIALOG GOES NOW, NOT WHEN THE SERVER ANSWERS.
    //
    // Checking a code is a password hash: about a third of a second of
    // deliberate work on the server, before the network. Holding a modal over
    // the screen for that is holding the counter still for it, and the whole
    // point of a four-digit code is that authorising costs four keystrokes.
    //
    // So the last keystroke closes it. The action behind it carries its own
    // waiting mark — the line being priced sits with a spinner and its old
    // figure until the server settles it — which is where somebody is already
    // looking, and it is the honest place to say the work is not finished.
    //
    // Refusal brings the dialog back with what the server said, the boxes
    // empty and shaking. That is the cost of this, and it is the right way
    // round: the common case is a correct code, and it is the common case that
    // should be instant.
    setSent(true);
    try {
      const res = await api.post<{ token: string }>("/api/step-up", {
        action,
        ...(usePassword ? { password: credential } : { pin: credential }),
        approver: approver.trim(),
        context,
      });
      onGranted(res.token);
    } catch (err: any) {
      setSent(false);
      // The server's refusal is the useful message — "not permitted to approve",
      setPinRefused(!usePassword);
      // "needs a second person", "that password was not accepted", so it is
      // shown as written rather than replaced with something generic.
      setError(err.message);
      setPassword("");
      // The boxes shake, then empty themselves. Retyping over a wrong PIN one
      // digit at a time is how the second attempt becomes a third.
      setPin("");
      // Said as well as shown. The dialog was gone, the eye had moved on, and
      // a prompt that silently reappears is one somebody types into twice.
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  /* Making a code. The same dialog, a step deeper: the action, the context and
     the approver's name are all still held above, so closing this returns to a
     prompt that has not lost anything. */
  if (making) {
    const matched = newPin.length === PIN_LENGTH && againPin.length === PIN_LENGTH;
    return (
      <div className="modal-backdrop" onClick={(e) => e.stopPropagation()}>
        <form className="modal su-make" onClick={(e) => e.stopPropagation()}
              onSubmit={makeTheCode}>
          <h2><Key size={18} weight="fill" /> Choose a code</h2>
          <p className="muted">
            Four digits, typed instead of a password when something needs
            approving. It signs one action; it never signs anybody in, so it
            cannot open a session anywhere.
          </p>
          <p className="muted small">
            You will come straight back to {spec ? spec.name.toLowerCase() : "what you were doing"},
            with everything still filled in.
          </p>

          {error && (
            <div className="alert error su-error" role="alert">
              <Warning size={16} weight="fill" />
              <span>{error}</span>
            </div>
          )}

          <label htmlFor="su-make-who">
            Whose code
            <input id="su-make-who" value={makeAs} autoComplete="off" autoFocus={!makeAs}
                   onChange={(e) => setMakeAs(e.target.value)} />
          </label>
          <label htmlFor="su-make-pass">
            {/* Their own password, because a code somebody else chose attributes
                an action to the wrong person, which is the only thing the code
                is for. */}
            Their password
            <input id="su-make-pass" type="password" value={password} autoComplete="off"
                   autoFocus={!!makeAs}
                   onChange={(e) => setPassword(e.target.value)} />
          </label>

          <div className="su-pin">
            <span className="su-pin-label">New code</span>
            <PinInput length={PIN_LENGTH} value={newPin} disabled={busy}
                      onChange={(v) => { setNewPin(v); setError(""); }} />
          </div>
          <div className="su-pin">
            <span className="su-pin-label">Again</span>
            <PinInput length={PIN_LENGTH} value={againPin} disabled={busy}
                      invalid={matched && newPin !== againPin}
                      onChange={(v) => { setAgainPin(v); setError(""); }} />
          </div>

          <p className="muted small">
            Not 1234, 0000, or four of the same digit. Those are the first three
            anybody tries. Five wrong attempts locks it for ten minutes.
          </p>

          <div className="modal-actions">
            <button type="button" className="btn ghost"
                    onClick={() => { setMaking(false); setError(""); setPassword(""); }}>
              Back
            </button>
            <BusyButton type="submit" className="btn primary" busyLabel="Setting it…"
                        disabled={!matched || !password || !makeAs.trim()}
                        onClick={makeTheCode}>
              Set the code
            </BusyButton>
          </div>
        </form>
      </div>
    );
  }

  // Away while the code is being checked. Not unmounted: everything typed is
  // still here, ready to be put back if the server refuses it.
  if (sent) return null;

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <form className="modal modal-narrow su" onClick={(e) => e.stopPropagation()}
            onSubmit={submit}>
        <h2>{spec ? spec.name : "Authorisation required"}</h2>

        {madeFor && (
          <div className="alert ok su-made" role="status">
            <Key size={15} weight="fill" />
            <span>Code set for {madeFor}. Type it below.</span>
          </div>
        )}

        {needsSecondPerson ? (
          <p className="alert warn">
            This needs a second person. Ask{" "}
            {/* "an admin", not "a admin". It is the one line somebody reads
                with a customer waiting. */}
            {"aeiou".includes(spec!.approvers.join(" or ")[0]?.toLowerCase()) ? "an" : "a"}{" "}
            {spec!.approvers.join(" or ")} to enter
            their own username and password, not yours.
          </p>
        ) : null
        /* Nothing here. The action is named in the title, the boxes carry
           their own label and are the largest thing on the dialog, and a
           paragraph explaining why the software wants a code is a paragraph
           read once and skipped forever after, with a patient at the counter. */
        }

        {/* The demonstration's own code, said on the dialog that asks for it.
            Only a demo session ever gets one: the server answers "" to a real
            one, so nothing on a live till can quote a code at anybody. */}
        {demo && (
          <p className="alert ok su-demo">
            This is a demonstration. The code is <b>{demo.pin}</b>
            {needsSecondPerson && demo.approver_name
              ? <>, and {demo.approver_name} is the colleague to call over.</>
              : "."}
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
          /* Given the same weight as the code boxes, and the same width, so
             swapping between them does not resize the dialog under the hand
             that is typing. It was a default height field under a small label:
             the same dialog asking for the same thing, and one of the two
             looked like an afterthought. */
          <div className="su-pin su-pass">
            <span className="su-pin-label">
              {needsSecondPerson ? "Approver's password" : "Your password"}
            </span>
            <input
              type="password"
              className="su-pass-box"
              value={password}
              autoFocus={!needsSecondPerson}
              autoComplete="off"
              aria-label={needsSecondPerson ? "Approver's password" : "Your password"}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        ) : (
          <div className="su-pin" ref={pinBoxes}>
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
              onComplete={(typed) => {
                if (!needsSecondPerson || approver.trim()) submit(undefined, typed);
              }}
              autoFocus={!needsSecondPerson}
              invalid={pinRefused}
              disabled={busy}
            />
          </div>
        )}

        <div className="su-ways">
          <button
            type="button"
            className="ghost small su-swap"
            onClick={() => { setUsePassword((p) => !p); setPin(""); setPassword(""); }}
          >
            {usePassword ? "Use a PIN instead" : "Use a password instead"}
          </button>
          {/* ONLY WHEN THERE IS NO CODE.
              Made here rather than sent to a settings page, because the prompt
              is where somebody finds out they have not got one and it is also
              where the work they would lose by going to look is sitting.
              It used to be offered on every prompt, which put "set a code" in
              front of whoever was standing at the till whether or not the
              account already had one. Changing an existing code belongs on the
              owner's own profile, where it asks for the code being replaced. */}
          {offerToMake && (
            <button
              type="button"
              className="ghost small su-make-offer is-needed"
              onClick={startMaking}
            >
              <Key size={13} weight="fill" />
              Set a code now
            </button>
          )}
        </div>

        {/* Kept, because it is the sentence that makes typing a code
            reasonable rather than a nuisance, and cut to the two facts it
            actually carries: once, and on the record. */}
        {spec && (
          <p className="muted small">This one action, and it is recorded.</p>
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
