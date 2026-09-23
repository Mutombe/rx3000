/** What the funder calls this medicine, where the dispenser can fix it.
 *
 *  A claim line is adjudicated on a NAPPI code. The funder matches the code,
 *  not the name: a line with none is rejected outright, and the pharmacy finds
 *  out weeks later in a remittance, when the medicine is gone and so is the
 *  patient. Cimas publishes a list; most schemes never say anything, and none of
 *  them tell a pharmacy when a code changes.
 *
 *  Three rules decide everything here, and the first is the one that keeps the
 *  screen simple:
 *
 *  1. **It only exists when there is a scheme.** On a cash script — most of them
 *     — the code is nowhere at all. Nothing to read, nothing to skip past.
 *  2. **Silence when it is known, a mark when it is not.** A column of codes
 *     that are nearly always right is a column nobody reads. What earns space is
 *     the line that will be rejected.
 *  3. **Fixing it teaches the catalogue.** The code is the same on every script
 *     that medicine will ever appear on, so it is kept against the product and
 *     the next dispenser is answered — the way an unrecognised barcode is.
 */
import { useCallback, useEffect, useState } from "react";
import { Warning } from "@phosphor-icons/react";
import { api, errorText } from "../api";
import { useToast } from "./Toast";

export interface SchemeCode {
  product_id: number;
  code: string;
  /** "scheme" — this funder's own; "general" — the pharmacy's NAPPI standing
   *  in; "none" — nothing, and the claim line will be rejected. */
  origin: "scheme" | "general" | "none";
  source: string;
  set_by: string;
  updated_at: string;
}

/** Every line's code in one call, refreshed when the basket or the scheme moves.
 *
 *  One request for the basket rather than one per line: this is read while a
 *  script is being typed, and a round trip a line on the dispensary screen is
 *  the difference between a list that keeps up and one that flickers.
 */
export function useSchemeCodes(medicalAidId: number | null, productIds: number[]) {
  const [codes, setCodes] = useState<Record<number, SchemeCode>>({});
  const key = `${medicalAidId ?? ""}|${productIds.join(",")}`;

  const reload = useCallback(async () => {
    if (!medicalAidId || productIds.length === 0) { setCodes({}); return; }
    try {
      const said = await api.post<{ codes: SchemeCode[] }>("/api/scheme-codes", {
        medical_aid_id: medicalAidId, product_ids: productIds,
      });
      const next: Record<number, SchemeCode> = {};
      for (const row of said.codes || []) next[row.product_id] = row;
      setCodes(next);
    } catch {
      // A code that cannot be read must never stop anybody dispensing. It
      // simply does not appear, and the claim carries what the server decides.
      setCodes({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => { void reload(); }, [reload]);
  return { codes, reload };
}

/** Save a code against a medicine for this funder, for good. */
export async function rememberCode(medicalAidId: number, productId: number, code: string) {
  return api.put<SchemeCode & { message?: string }>(
    `/api/scheme-codes/${medicalAidId}/${productId}`, { code });
}

/** The mark on a script line that will be rejected as it stands.
 *
 *  Drawn only when there is a scheme AND no code at all. A line standing on the
 *  pharmacy's own NAPPI is not marked: it has a code, the claim will carry it,
 *  and a warning that fires on the ordinary case is a warning people learn to
 *  look past.
 */
export function NoCodeMark({ known, scheme, onFix }: {
  known?: SchemeCode;
  scheme: string;
  onFix: () => void;
}) {
  if (!known || known.origin !== "none") return null;
  return (
    <span
      className="rx-nocode"
      role="button"
      tabIndex={-1}
      title={`${scheme} has no code for this medicine, so this line will be rejected.\n`
        + "Click to say what it is."}
      aria-label={`No ${scheme} code. This line will be rejected. Fix it`}
      onClick={(e) => { e.stopPropagation(); onFix(); }}
    >
      <Warning size={13} weight="fill" />
    </span>
  );
}

/** The field itself: read it, correct it, and it is kept for everybody.
 *
 *  Used in the line editor, where the dispenser is holding the box, and on the
 *  billing step, where the claim is about to go.
 */
export default function SchemeCodeField({
  medicalAidId, scheme, productId, productName, known, onSaved, compact,
}: {
  medicalAidId: number;
  scheme: string;
  productId: number;
  productName: string;
  known?: SchemeCode;
  onSaved: () => void;
  /** One line, for the billing list, rather than a labelled field. */
  compact?: boolean;
}) {
  const toast = useToast();
  const [typed, setTyped] = useState(known?.code ?? "");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => { setTyped(known?.code ?? ""); }, [known?.code, productId]);

  const missing = !known || known.origin === "none";
  const borrowed = known?.origin === "general";

  async function save() {
    const next = typed.trim();
    if (next === (known?.code ?? "").trim()) { setOpen(false); return; }
    setBusy(true);
    try {
      const said = await rememberCode(medicalAidId, productId, next);
      toast.ok(said?.message || `${scheme} will be billed ${next} for ${productName}.`);
      onSaved();
      setOpen(false);
    } catch (e) {
      toast.error(errorText(e));
      setTyped(known?.code ?? "");
    } finally {
      setBusy(false);
    }
  }

  const field = (
    <span className={`sc-field${missing ? " is-missing" : ""}`}>
      <input
        className="sc-input"
        inputMode="numeric"
        maxLength={24}
        value={typed}
        disabled={busy}
        placeholder="Not known"
        aria-label={`${scheme} code for ${productName}`}
        onChange={(e) => setTyped(e.target.value.replace(/[^0-9]/g, ""))}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); void save(); }
          if (e.key === "Escape") { e.preventDefault(); setTyped(known?.code ?? ""); setOpen(false); }
        }}
        onBlur={() => void save()}
      />
    </span>
  );

  if (compact) {
    // The billing list: the code, or the reason there is none, on one line.
    if (missing && !open) {
      // Two words, because this sits in the width of the field it replaces and
      // a scheme called "AHSS Zimbabwe" would push the medicine's name off the
      // row. The whole sentence is on the control for anybody who wants it.
      return (
        <button type="button" className="sc-missing" onClick={() => setOpen(true)}
                title={`${scheme} has no code for ${productName}, so this line `
                  + "will be rejected. Type it from the box."}>
          <Warning size={12} weight="fill" /> add code
        </button>
      );
    }
    return (
      <span className="sc-compact">
        {field}
        {borrowed && (
          <em className="sc-borrowed" title="The pharmacy's own NAPPI, standing in.
No code has been published or typed for this scheme.">
            the shop's own
          </em>
        )}
      </span>
    );
  }

  return (
    <div className="field sc-line">
      <label htmlFor={`sc-${productId}`}>{scheme} code</label>
      {field}
      <span className="hint">
        {missing
          ? <><Warning size={12} weight="fill" /> {scheme} cannot identify this
              medicine, so the claim line is rejected. The code is on the box.</>
          : borrowed
            ? <>The pharmacy's own NAPPI, standing in. Type {scheme}'s own if it differs.</>
            : <>Kept for every script{known?.set_by ? `, set by ${known.set_by}` : ""}
                {known?.source ? ` · ${known.source}` : ""}</>}
      </span>
    </div>
  );
}
