import { useEffect, useState } from "react";
import { api } from "../api";

/** Who this installation actually is.
 *
 *  Receipts used to be printed with the string "RX3000 Pharmacy" hardcoded at
 *  every call site — the name of the software, in the place a customer looks for
 *  the name of the shop. It is the same defect as any other value nobody writes:
 *  it renders, it looks deliberate, and it is wrong at every pharmacy that is not
 *  us. The backend has always known the answer, on /api/jurisdiction.
 *
 *  Fetched once per page load and shared, because every till would otherwise ask
 *  for it on each sale.
 */
export interface PharmacyIdentity {
  name: string;
  regNo: string;
}

const FALLBACK: PharmacyIdentity = { name: "", regNo: "" };

let cached: Promise<PharmacyIdentity> | null = null;

export function pharmacyIdentity(): Promise<PharmacyIdentity> {
  if (!cached) {
    cached = api
      .get<{ pharmacy_name?: string; pharmacy_reg_no?: string }>("/api/jurisdiction")
      .then((d) => ({ name: d.pharmacy_name ?? "", regNo: d.pharmacy_reg_no ?? "" }))
      .catch(() => {
        // A failed lookup must not be remembered as "this pharmacy has no name" —
        // the next receipt should try again rather than print a blank header.
        cached = null;
        return FALLBACK;
      });
  }
  return cached;
}

export function usePharmacy(): PharmacyIdentity {
  const [identity, setIdentity] = useState<PharmacyIdentity>(FALLBACK);
  useEffect(() => {
    let live = true;
    pharmacyIdentity().then((v) => { if (live) setIdentity(v); });
    return () => { live = false; };
  }, []);
  return identity;
}
