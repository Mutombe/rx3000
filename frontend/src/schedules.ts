/** What this country calls its medicine schedules.
 *
 *  A schedule number is an internal ordinal. What a pharmacist reads, says out
 *  loud and writes on a label is a code, and the codes are not the same from
 *  one country to the next:
 *
 *      schedule   South Africa   Zimbabwe
 *             0   S0             HR     household remedy
 *             1   S1             P      pharmacy medicine
 *             2   S2             PIM    pharmacist-initiated medicine
 *             5   S5             PP10   prescription preparation, Tenth Schedule
 *             6   S6             N      narcotic / dangerous drug
 *
 *  The jurisdiction pack has said so since it was written — `SchedulePolicy`
 *  carries a `code` field whose docstring is "callers must display `code`,
 *  never `schedule`, or a Zimbabwean pharmacy will be shown a South African
 *  label" — and then every screen rendered `S{schedule}` anyway. So a pharmacy
 *  in Harare was told its codeine was "S5", which is not what the law there
 *  calls it, not what is printed on the box, and not what an inspector asks
 *  about.
 *
 *  It is wrong in the way that is hardest to notice: "S5" is a plausible thing
 *  to see, it sorts the medicines correctly, and it is only wrong about the one
 *  thing the badge exists to say.
 *
 *  Fetched once for the whole application and shared, because it is the same
 *  answer on every screen and it changes when the country does — which is
 *  never, within an installation.
 */
import { useEffect, useState } from "react";

import { api } from "./api";
import type { SchedulePolicy } from "./types";

let known: Record<number, string> | null = null;
let asking: Promise<Record<number, string>> | null = null;
const waiting = new Set<() => void>();

/** The codes, fetched at most once however many screens ask at once. */
function fetchCodes(): Promise<Record<number, string>> {
  if (asking) return asking;
  asking = api.get<SchedulePolicy[]>("/api/dispensing/policy")
    .then((policies) => {
      const map: Record<number, string> = {};
      for (const p of policies || []) {
        if (p.code) map[p.schedule] = p.code;
      }
      known = map;
      // Everything already on screen re-renders with the real codes.
      for (const wake of waiting) wake();
      return map;
    })
    .catch(() => {
      // A label that cannot be read must never stop anybody dispensing. The
      // fallback below is used, and the next screen asks again.
      asking = null;
      return {};
    });
  return asking;
}

/** The code for a schedule, as this country writes it.
 *
 *  Falls back to `S{n}` only while the pack is still loading or if it could not
 *  be read. That fallback is deliberately the old behaviour rather than a blank:
 *  a badge that flickers from "S5" to "PP10" is untidy, and a badge that
 *  flickers from nothing to "PP10" makes the row jump.
 */
export function scheduleCode(schedule: number | null | undefined): string {
  const n = Number(schedule ?? 0);
  return known?.[n] ?? `S${n}`;
}

/** Subscribe a component to the codes, so it redraws once they arrive. */
export function useScheduleCodes(): (schedule: number | null | undefined) => string {
  const [, bump] = useState(0);
  useEffect(() => {
    if (known) return;
    const wake = () => bump((n) => n + 1);
    waiting.add(wake);
    void fetchCodes();
    return () => { waiting.delete(wake); };
  }, []);
  return scheduleCode;
}

/** A range, for the places that name two: "S5 and S6", or "PP10 and N".
 *
 *  The joiner is a parameter because both readings occur and they are not
 *  interchangeable. A register covers PP10 AND N; a single item on a shelf is
 *  PP10 OR N, and "a PP10 and N item" describes one box that is somehow both.
 */
export function scheduleRange(from: number, to: number, joiner = "and"): string {
  return `${scheduleCode(from)} ${joiner} ${scheduleCode(to)}`;
}
