/** Paging controls that always say how much there is.
 *
 *  The count is the point. A pager that only offers Next and Previous tells you
 *  nothing about whether you are looking at most of the data or a tenth of it,
 *  and a list quietly cut short is the failure this component exists to prevent:
 *  it looks complete, so nobody goes looking for the rest.
 *
 *  Hence "Showing 1–50 of 159" is not a nicety here, it is the primary content,
 *  and the buttons are secondary to it.
 */
import { CaretLeft, CaretRight } from "@phosphor-icons/react";
import Select from "./Select";

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
  has_more: boolean;
  showing_from: number;
  showing_to: number;
}

const SIZES = [25, 50, 100, 200];

export default function Pagination({
  meta,
  onPage,
  onPerPage,
  noun = "records",
}: {
  meta: Pick<Paged<unknown>, "total" | "page" | "pages" | "per_page" | "showing_from" | "showing_to">;
  onPage: (page: number) => void;
  onPerPage?: (size: number) => void;
  /** What is being counted, so the sentence reads properly. */
  noun?: string;
}) {
  // One page of results needs no controls, but it still needs the count — that
  // is what confirms nothing is hidden.
  const single = meta.pages <= 1;

  return (
    <div className="pager">
      <div className="pager-count">
        {meta.total === 0 ? (
          `No ${noun}`
        ) : (
          <>
            Showing <b>{meta.showing_from}–{meta.showing_to}</b> of{" "}
            <b>{meta.total.toLocaleString()}</b> {noun}
          </>
        )}
      </div>

      <div className="pager-controls">
        {onPerPage && (
          <label className="pager-size">
            Rows
            <Select
              value={String(meta.per_page ?? "")}
              onChange={(__value) => onPerPage(Number(__value))}
              options={SIZES.map((n) => ({ value: String(n), label: String(n) }))}
            />
          </label>
        )}
        {!single && (
          <>
            <button
              className="ghost small"
              onClick={() => onPage(meta.page - 1)}
              disabled={meta.page <= 1}
              aria-label="Previous page"
            >
              <CaretLeft size={13} weight="bold" />
            </button>
            <span className="pager-pos">
              Page {meta.page} of {meta.pages}
            </span>
            <button
              className="ghost small"
              onClick={() => onPage(meta.page + 1)}
              disabled={meta.page >= meta.pages}
              aria-label="Next page"
            >
              <CaretRight size={13} weight="bold" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
