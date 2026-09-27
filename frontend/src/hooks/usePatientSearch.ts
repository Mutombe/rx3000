/** Looking a patient up by name, which seven screens were each doing by hand.
 *
 *  THE SAME SIX LINES, SEVEN TIMES, AND NOT THE SAME SIX LINES.
 *
 *  POS, Reminders, Reports, HelpDesk, LayBys, Authorisations and Dispense all
 *  had a two-character threshold, a query against `/api/patients`, and a list
 *  of hits. Three of them had no `.catch` at all, so a failed lookup was an
 *  unhandled rejection and an empty list — which every one of those screens
 *  renders as "no patient by that name". A cashier reads that and registers the
 *  patient again; a duplicate record is where a clinical history goes to die.
 *
 *  Only Dispense guarded against answers arriving out of order. On the other
 *  six, typing "Chi" then "Chido" could leave the hits for "Chi" on screen if
 *  the first request came back second, so the list could name somebody who
 *  does not match what is in the box.
 *
 *  So the failure and the race are fixed once, here, and the screens keep
 *  their own words for what an empty list means.
 *
 *  `failed` is the part worth spending a line of UI on. It is the difference
 *  between "this pharmacy has no record of them" and "nobody asked".
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Patient } from "../types";

export interface PatientSearch {
  /** What is in the box. */
  q: string;
  setQ: (value: string) => void;
  /** Who matched. Empty while the box holds fewer than two characters. */
  hits: Patient[];
  /** The lookup could not be run, so `hits` is not an answer about anybody. */
  failed: boolean;
  /** Box emptied and hits dropped, for when one has been picked. */
  clear: () => void;
}

export function usePatientSearch(limit = 6): PatientSearch {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Patient[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); setFailed(false); return; }
    // `stale` closes over this run of the effect. The cleanup sets it before
    // the next run starts, so an answer to a question nobody is asking any
    // more is dropped instead of rendered.
    let stale = false;
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(q)}&limit=${limit}`)
      .then((found) => { if (!stale) { setHits(found); setFailed(false); } })
      .catch(() => { if (!stale) { setHits([]); setFailed(true); } });
    return () => { stale = true; };
  }, [q, limit]);

  const clear = useCallback(() => {
    setQ(""); setHits([]); setFailed(false);
  }, []);

  return { q, setQ, hits, failed, clear };
}
