/** The product catalogue, kept locally so a till can still sell when the line drops.
 *
 *  Refreshed while the connection is up, so that the copy on disk is always the
 *  one from the last good moment rather than something assembled in a hurry
 *  once things are already going wrong. A till that only caches when it notices
 *  it is offline has nothing to cache with.
 *
 *  What is deliberately **not** here: anything clinical. This holds names,
 *  barcodes, prices and a stock figure — enough to sell a bottle of shampoo and
 *  not nearly enough to dispense. Keeping scripts, repeats and patient history
 *  off the device is what makes the offline block on dispensing a real boundary
 *  rather than a preference, and it means a till stolen from a counter carries
 *  no patient data.
 */
import { api } from "../api";
import { local, meta, setMeta, STORE_PRODUCTS } from "./db";

export interface CachedProduct {
  id: number;
  name: string;
  barcode: string;
  nappi_code: string;
  category: string;
  schedule: number;
  strength: string;
  unit_price: number;
  cost_price: number;
  /** As at the last sync. Advisory offline, never authoritative. */
  quantity_on_hand: number;
}

const LAST_SYNC = "catalogue_synced_at";
const COUNT = "catalogue_count";

/** A page at a time. The offline catalogue is the one thing that genuinely wants
 *  every row, and it used to ask for them in a single `?limit=100000` request.
 *  The server now clamps any size parameter to 200, so that request quietly
 *  returned 200 products and the till would have gone offline believing the
 *  pharmacy stocked two hundred things.
 *
 *  Wanting everything and asking for everything in one request are different: the
 *  paged endpoint reports the total, so this can walk it and know when it has the
 *  lot rather than guessing from the size of the reply. */
const PAGE = 200;

async function fetchEveryProduct(): Promise<any[]> {
  const all: any[] = [];
  let page = 1;
  for (;;) {
    const res = await api.get<{ items: any[]; total: number; pages: number }>(
      `/api/products/paged?page=${page}&per_page=${PAGE}`);
    all.push(...(res.items ?? []));
    // Stop on the reported page count, not on a short page: a page that comes
    // back short because a product was deleted mid-sync is not the end.
    if (!res.items?.length || page >= (res.pages ?? 1)) {
      if (res.total && all.length < res.total && page < 500) {
        page += 1;
        continue;
      }
      return all;
    }
    page += 1;
  }
}

/** Pull the catalogue down and replace the local copy. */
export async function sync(): Promise<{ count: number; at: string }> {
  const rows = await fetchEveryProduct();
  const cached: CachedProduct[] = rows.map((p) => ({
    id: p.id,
    name: p.name ?? "",
    barcode: p.barcode ?? "",
    nappi_code: p.nappi_code ?? "",
    category: p.category ?? "",
    schedule: p.schedule ?? 0,
    strength: p.strength ?? "",
    unit_price: p.unit_price ?? 0,
    cost_price: p.cost_price ?? 0,
    quantity_on_hand: p.quantity_on_hand ?? 0,
  }));
  await local.replaceAll(STORE_PRODUCTS, cached);
  const at = new Date().toISOString();
  await setMeta(LAST_SYNC, at);
  await setMeta(COUNT, cached.length);
  return { count: cached.length, at };
}

export async function status(): Promise<{ count: number; at: string | null }> {
  return {
    count: (await meta<number>(COUNT)) ?? (await local.count(STORE_PRODUCTS)),
    at: (await meta<string>(LAST_SYNC)) ?? null,
  };
}

/** Look a scanned code up in the local copy.
 *
 *  Matches the server's order — barcode, then NAPPI — so a code that resolves
 *  one way online does not resolve a different way offline. A till that finds a
 *  different product depending on the state of the network is worse than one
 *  that finds nothing.
 *
 *  The alias table is not cached, so alternate barcodes taught to the system
 *  will miss offline. That is a real limitation and is surfaced to the operator
 *  rather than papered over: the code is not wrong, we simply cannot check it.
 */
export async function lookup(code: string): Promise<CachedProduct | null> {
  const clean = code.trim();
  if (!clean) return null;
  const all = await local.all<CachedProduct>(STORE_PRODUCTS);
  const digits = clean.replace(/^0+/, "");

  const byBarcode = all.find(
    (p) => p.barcode && (p.barcode === clean || p.barcode.replace(/^0+/, "") === digits),
  );
  if (byBarcode) return byBarcode;

  const byNappi = all.find((p) => p.nappi_code && p.nappi_code === clean);
  if (byNappi) return byNappi;
  return null;
}

/** Name search over the local copy, for when a label will not scan. */
export async function search(term: string, limit = 8): Promise<CachedProduct[]> {
  const needle = term.trim().toLowerCase();
  if (needle.length < 2) return [];
  const all = await local.all<CachedProduct>(STORE_PRODUCTS);
  return all
    .filter((p) => p.name.toLowerCase().includes(needle))
    .slice(0, limit);
}

/** Whether there is enough here to trade on. */
export async function usable(): Promise<boolean> {
  return (await local.count(STORE_PRODUCTS)) > 0;
}
