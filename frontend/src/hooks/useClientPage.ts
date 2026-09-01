import { useEffect, useMemo, useState } from "react";
import { Paged } from "../components/Pagination";

/** Page a list that is already in memory.
 *
 *  For the lists whose endpoint deliberately returns everything: a stock
 *  valuation has to sum every line to state a total, and a reorder sheet has to
 *  know the whole shortfall before anyone decides what to buy. Fetching a page
 *  at a time would make those totals wrong or a second round trip.
 *
 *  What was wrong was rendering all of it — 433 rows of valuation in the DOM,
 *  with no way to move through them and nothing saying how many there were. The
 *  data stays whole; only the render is bounded.
 *
 *  The totals shown beside these tables are computed over the full array by the
 *  caller, never over `items` — a footer that silently totals the visible page
 *  is the most misleading thing a report can do.
 */
export function useClientPage<T>(rows: T[], perPage = 25): {
  items: T[];
  meta: Paged<T>;
  setPage: (p: number) => void;
} {
  const [page, setPage] = useState(1);
  const pages = Math.max(1, Math.ceil(rows.length / perPage));

  // The set changed under us, a filter, a refresh, and page 9 of the old set
  // is not page 9 of this one.
  useEffect(() => { setPage((p) => Math.min(p, pages)); }, [pages]);

  const items = useMemo(
    () => rows.slice((page - 1) * perPage, page * perPage),
    [rows, page, perPage],
  );

  return {
    items,
    meta: {
      items,
      total: rows.length,
      page,
      pages,
      per_page: perPage,
      showing_from: rows.length ? (page - 1) * perPage + 1 : 0,
      showing_to: Math.min(page * perPage, rows.length),
      has_more: page < pages,
    } as Paged<T>,
    setPage,
  };
}
