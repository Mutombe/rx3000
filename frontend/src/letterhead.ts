/** The pharmacy's own particulars, fetched once and remembered.
 *
 *  Every printed document needs the same eight facts about the pharmacy, and
 *  a document is printed from a dozen different screens. Without one place to
 *  hold them, each screen assembles its own header out of whatever settings it
 *  happens to know about, which is how one statement carries the VAT number
 *  and the next one does not.
 *
 *  Cached at module scope rather than in a store: these change about once a
 *  year, and a second request for them on every print is a second of delay
 *  before a window that the user is waiting on.
 */
import { api } from "./api";
import type { Letterhead } from "./document";

let cached: Letterhead | null = null;
let inflight: Promise<Letterhead> | null = null;

export function letterhead(): Promise<Letterhead> {
  if (cached) return Promise.resolve(cached);
  if (!inflight) {
    inflight = api.get<Letterhead>("/api/profile/company/letterhead")
      .then((d) => { cached = d; return d; })
      // A document without a letterhead is worse than no document, but it is
      // still better than a print button that silently does nothing.
      .catch(() => ({ display_name: "" } as Letterhead))
      .finally(() => { inflight = null; });
  }
  return inflight;
}

/** Called after the branding is edited, so the next print reflects it. */
export function forgetLetterhead() { cached = null; }
