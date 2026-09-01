/** How long is left of a demo, and what happens when it runs out.
 *
 *  Counted from an absolute time the server issued, not from a duration held in
 *  the browser. A client counting down from "four hours" drifts, and a laptop
 *  that was asleep for two of them wakes up insisting there is plenty of time
 *  while the server has already closed the account. Re-deriving the remainder
 *  from `demo_expires_at` on every tick makes a sleeping machine correct the
 *  moment it wakes.
 *
 *  At zero it signs the visitor out itself rather than waiting for their next
 *  action to fail. Being told a demo has ended is a fair ending; clicking Save
 *  on twenty minutes of work and being told the same thing is not.
 *
 *  Nothing renders for an ordinary account, which is every account in a
 *  pharmacy that has bought this.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { setToken } from "../api";
import type { User } from "../types";

/** Two steps of urgency, not a gradient. A bar that changes every minute is
 *  decoration, and decoration is the thing people stop reading. */
const URGENT_SECONDS = 10 * 60;
const CRITICAL_SECONDS = 2 * 60;

function remaining(expires: string): number {
  // The server sends naive UTC. Appending Z rather than trusting the browser to
  // guess: read as local time, a four-hour demo in Harare would appear to have
  // expired two hours before it started.
  const at = Date.parse(expires.endsWith("Z") ? expires : `${expires}Z`);
  if (Number.isNaN(at)) return 0;
  return Math.max(0, Math.round((at - Date.now()) / 1000));
}

function spell(total: number): string {
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export default function DemoBar({ user }: { user: User | null }) {
  const expires = user?.is_demo ? user.demo_expires_at ?? null : null;
  /* A tick, and the remainder derived from it.
     Holding the remainder in state instead put a whole render between "we now
     know when this expires" and "and here is how long that is", and in that
     render the remainder was still its initial zero, so the effect below saw
     zero seconds left and signed the visitor out the instant they arrived.
     Deriving it means the two can never disagree. */
  const [, tick] = useState(0);
  const navigate = useNavigate();
  const left = expires ? remaining(expires) : null;

  useEffect(() => {
    if (!expires) return;
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [expires]);

  useEffect(() => {
    if (left === null || left > 0) return;
    // Ended. Out, with a reason, rather than left on a page where the next click
    // returns a 401 nobody can interpret.
    setToken(null);
    navigate("/login", { state: { demoEnded: true } });
  }, [left, navigate]);

  if (left === null) return null;

  const tone = left <= CRITICAL_SECONDS ? " is-critical"
    : left <= URGENT_SECONDS ? " is-urgent" : "";

  return (
    <div className={`demo-bar${tone}`} role="status">
      <span className="demo-clock">{spell(left)}</span>
      <span>
        left on this demo.
        <span className="demo-why">
          {" "}Everything you enter is kept when it ends.
        </span>
      </span>
    </div>
  );
}
