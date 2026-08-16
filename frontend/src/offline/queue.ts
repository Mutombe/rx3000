/** Sales taken while the line was down, waiting to be posted.
 *
 *  The dangerous part of an offline queue is not storing the sale. It is
 *  posting it twice.
 *
 *  A flush runs when the connection returns, which is exactly when the network
 *  is least reliable. A request can be received and applied by the server and
 *  still fail on the way back — a dropped response, a proxy timeout, the tab
 *  closing. The queue cannot tell that apart from a request that never arrived,
 *  so it retries, and the sale is posted a second time: stock decremented
 *  twice, the day's takings overstated, and a phantom transaction on a
 *  patient's history.
 *
 *  So every queued sale carries a reference generated **before** the first
 *  attempt and reused on every retry, and the server treats a reference it has
 *  already seen as "you already told me this" rather than as a new sale. The
 *  queue is therefore safe to replay as often as it likes, which is what makes
 *  it safe to retry aggressively.
 *
 *  Nothing here is removed from the queue until the server has confirmed it.
 *  A sale that cannot be posted stays, with its reason, and is shown to a human
 *  rather than dropped.
 */
import { api } from "../api";
import { local, STORE_QUEUE } from "./db";

export interface QueuedSale {
  /** Client-generated, stable across retries. This is the idempotency key. */
  ref: string;
  /** The sale payload, exactly as the online path would have posted it. */
  payload: unknown;
  created_at: string;
  attempts: number;
  last_error: string;
  /** Set once the server has confirmed it; the row is then removed. */
  posted_at?: string;
}

/** A reference that will not collide between tills or across a reset.
 *
 *  `crypto.randomUUID` where it exists. The fallback is not merely random: it
 *  carries the time, so two tills that both fall back cannot produce the same
 *  reference in the same millisecond by chance alone.
 */
export function newRef(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return `off_${c.randomUUID()}`;
  const rand = Math.random().toString(36).slice(2, 10);
  return `off_${Date.now().toString(36)}_${rand}`;
}

export async function enqueue(payload: unknown): Promise<QueuedSale> {
  const row: QueuedSale = {
    ref: newRef(),
    payload,
    created_at: new Date().toISOString(),
    attempts: 0,
    last_error: "",
  };
  await local.put(STORE_QUEUE, row);
  return row;
}

export function pending(): Promise<QueuedSale[]> {
  return local.all<QueuedSale>(STORE_QUEUE);
}

export function pendingCount(): Promise<number> {
  return local.count(STORE_QUEUE);
}

export interface FlushResult {
  posted: number;
  failed: number;
  remaining: number;
  errors: string[];
}

let flushing = false;

/** Post everything waiting. Safe to call repeatedly and from several places.
 *
 *  Guarded against running twice at once, because the connection returning and
 *  the operator pressing "retry" are two events that routinely arrive together,
 *  and two concurrent flushes would each read the same queue.
 */
export async function flush(): Promise<FlushResult> {
  if (flushing) return { posted: 0, failed: 0, remaining: await pendingCount(), errors: [] };
  flushing = true;
  const result: FlushResult = { posted: 0, failed: 0, remaining: 0, errors: [] };

  try {
    const rows = await pending();
    // Oldest first: the order they were taken in is the order they should hit
    // the books, and stock movements read very oddly otherwise.
    rows.sort((a, b) => a.created_at.localeCompare(b.created_at));

    for (const row of rows) {
      try {
        await api.post("/api/pos/sales", {
          ...(row.payload as object),
          // The server keys on this. Sending it again is how a retry stays safe.
          client_ref: row.ref,
          taken_offline_at: row.created_at,
        });
        await local.del(STORE_QUEUE, row.ref);
        result.posted += 1;
      } catch (e: any) {
        const message = e?.message || "Unknown error";
        row.attempts += 1;
        row.last_error = message;
        await local.put(STORE_QUEUE, row);
        result.failed += 1;
        if (!result.errors.includes(message)) result.errors.push(message);
        // A failure here is usually the line going down again mid-flush, in
        // which case the rest will fail too and hammering them just burns
        // battery. Stop and let the next reconnect try again.
        break;
      }
    }
    result.remaining = await pendingCount();
    return result;
  } finally {
    flushing = false;
  }
}

/** Drop a sale that will never post, deliberately and by a person.
 *
 *  Kept separate from the automatic path and never called by it. Something the
 *  server keeps refusing is a decision for a human — the money was taken, and a
 *  queue that quietly discards its own failures is worse than one that stalls.
 */
export function discard(ref: string) {
  return local.del(STORE_QUEUE, ref);
}
