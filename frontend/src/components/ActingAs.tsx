/** A standing reminder that you are not yourself at the moment.
 *
 *  WHY THIS EXISTS BEFORE THE BUTTON THAT NEEDS IT.
 *
 *  `POST /api/hq/impersonate/{user_id}` has been in the server since head
 *  office was written and had no caller anywhere. Its docstring says the token
 *  carries both names so "every row written while it lasts records who was
 *  really doing it", and that `imp_name` "is read by the banner, so the person
 *  acting cannot forget they are".
 *
 *  There was no banner. Nothing in the product read `imp_name` at all. So the
 *  feature was half built, and the missing half was the safety half: somebody
 *  from head office would have become a cashier in Bulawayo for half an hour
 *  with nothing on screen saying so, which is how a support session turns into
 *  a real void at a real till under somebody else's name.
 *
 *  WHAT IT HAS TO SURVIVE.
 *
 *  A reload, a route change, and a closed tab, because the token does. It reads
 *  the claim out of the token rather than being told by whoever started the
 *  session: a banner that depends on being switched on is a banner that is off
 *  after a refresh, which is exactly when somebody has forgotten.
 *
 *  AND IT HAS TO OFFER THE WAY BACK.
 *
 *  Thirty minutes is long enough to forget and short enough to strand
 *  somebody mid-sentence. The head office session is kept aside when the swap
 *  happens and put back by the button here, so returning is one press rather
 *  than signing in again.
 */
import { useEffect, useState } from "react";
import { ArrowUUpLeft, Eye } from "@phosphor-icons/react";
import { getToken, setToken } from "../api";
import { readStored, writeStored } from "../storage";

/** Where head office's own session waits while it is somebody else. */
export const OWN_SESSION = "own_token";

/** The claims this banner needs, read straight from the token.
 *
 *  Decoded rather than verified, deliberately: the server verifies every
 *  request and this is a label on a screen. A tampered token buys a liar a
 *  misleading banner and no access whatsoever.
 */
function actingAs(): { name: string; until: number } | null {
  const raw = getToken();
  if (!raw) return null;
  try {
    const body = JSON.parse(
      atob(raw.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    if (!body?.imp) return null;
    return { name: String(body.imp_name || "somebody"), until: Number(body.exp || 0) };
  } catch {
    // A token this cannot read is one the server will refuse anyway.
    return null;
  }
}

export default function ActingAs() {
  const [who, setWho] = useState(actingAs);
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));

  // The countdown, and the moment it runs out. Both matter: a session that has
  // expired leaves the banner saying something untrue, and the person needs to
  // know before it goes rather than after.
  useEffect(() => {
    if (!who) return;
    const t = window.setInterval(() => {
      setNow(Math.floor(Date.now() / 1000));
      setWho(actingAs());
    }, 5_000);
    return () => window.clearInterval(t);
  }, [who]);

  if (!who) return null;

  const left = Math.max(0, who.until - now);
  const minutes = Math.ceil(left / 60);

  function comeBack() {
    const mine = readStored(OWN_SESSION);
    writeStored(OWN_SESSION, null);
    // Back to head office where there is a session to go back to, and out
    // altogether where there is not: continuing as somebody else because the
    // way back was lost is the one outcome worth refusing.
    setToken(mine ?? null);
    window.location.href = mine ? "/head-office" : "/";
  }

  return (
    <div className="acting-as" role="status">
      <Eye size={15} weight="fill" />
      <span>
        You are signed in as <b>someone else</b>. {who.name} started this, and
        everything done here is recorded against both names.
      </span>
      <span className="acting-left">
        {left > 0
          ? `${minutes} minute${minutes === 1 ? "" : "s"} left`
          : "This has run out"}
      </span>
      <button className="btn sm" onClick={comeBack}>
        <ArrowUUpLeft size={13} weight="bold" /> Be yourself again
      </button>
    </div>
  );
}
