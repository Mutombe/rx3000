/** Where the API lives.
 *
 *  Empty in development, where Vite proxies /api to the backend on the same
 *  origin. In a hosted deployment the static site and the API are two different
 *  services on two different hostnames, so a relative path would 404 on every
 *  request — the site would build, deploy, and be completely dead.
 *
 *  Trailing slash stripped, because `${BASE}/api/x` with a trailing slash gives
 *  a double slash that some proxies redirect and others reject.
 */
const BASE = resolveBase();

function resolveBase(): string {
  // The desktop shell injects the pharmacy's own server before any page script
  // runs. It wins over the build-time value, because a till on the premises
  // talks to the box in the back office, not to whatever host this bundle was
  // built against.
  const fromShell = (globalThis as any).__RX3000_SERVER__;
  if (typeof fromShell === "string" && fromShell.trim()) {
    return fromShell.trim().replace(/\/$/, "");
  }
  return (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
}

/** True when running inside the desktop shell rather than a browser tab. */
export const isDesktop = typeof (globalThis as any).__RX3000_SERVER__ === "string";

/** The same base, for code that does not go through `request` — the portals
 *  deliberately use bare fetch so they carry none of the staff session logic. */
export const apiBase = BASE;

let token: string | null = localStorage.getItem("rx3000_token");

export function setToken(t: string | null) {
  token = t;
  if (t) localStorage.setItem("rx3000_token", t);
  else localStorage.removeItem("rx3000_token");
}

export function getToken() {
  return token;
}

/** Turn whatever the server put in `detail` into a sentence a person can act on.
 *
 *  FastAPI reports validation failures as an array of objects, one per field.
 *  Stringifying that put raw JSON on screen — the reader saw
 *  `[{"type":"missing","loc":["body","quantity"],...}]` and learned nothing from
 *  it except that something had gone wrong. The field name and the reason are
 *  the only parts that help, so those are what is shown.
 */
function readableDetail(detail: unknown): string | null {
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d: any) => {
      if (typeof d === "string") return d;
      // `loc` is ["body", "field", ...]; the last segment names the field, and
      // the "body"/"query" prefix is plumbing the reader did not ask about.
      const loc = Array.isArray(d?.loc)
        ? d.loc.filter((x: unknown) => x !== "body" && x !== "query").join(" → ")
        : "";
      const msg = typeof d?.msg === "string" ? d.msg : "is not valid";
      return loc ? `${loc}: ${msg}` : msg;
    });
    // More than a couple of field errors at once is a form problem, not a
    // sentence — name the first and say how many others there are.
    return parts.length <= 2
      ? parts.join("; ")
      : `${parts[0]} (and ${parts.length - 1} other fields)`;
  }
  if (typeof detail === "object") {
    const d = detail as any;
    if (typeof d.message === "string") return d.message;
    if (typeof d.msg === "string") return d.msg;
  }
  return null;
}

/** A sentence for a response that did not explain itself. */
function statusWording(status: number): string {
  if (status === 403) return "You do not have permission to do that.";
  if (status === 404) return "That record no longer exists.";
  if (status === 409) return "Someone else changed this first. Reload and try again.";
  if (status === 413) return "That file is too large to upload.";
  if (status === 429) return "Too many requests just now. Wait a moment and retry.";
  if (status === 502 || status === 503 || status === 504)
    return "The server is not responding. It may be starting up — try again shortly.";
  if (status >= 500) return "Something went wrong at the server. Please try again.";
  return `The request was refused (${status}).`;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  stepUp?: string,
): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(stepUp ? { "X-Step-Up": stepUp } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) {
    setToken(null);
    window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = readableDetail(data.detail) ?? "";
    } catch {
      /* body was not JSON — fall through to the status-based wording */
    }
    // Never throw a blank message. HTTP/2 carries no status text, so
    // `res.statusText` is an empty string on any modern host — which produced a
    // toast with a count badge and no words at all. An error nobody can read is
    // worse than no error: it says something is wrong and refuses to say what.
    throw new ApiError(res.status, detail.trim() || statusWording(res.status));
  }
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  /** `stepUp` carries a single-use authorisation token for protected actions. */
  post: <T>(path: string, body?: unknown, stepUp?: string) =>
    request<T>("POST", path, body, stepUp),
  put: <T>(path: string, body?: unknown, stepUp?: string) =>
    request<T>("PUT", path, body, stepUp),
  delete: <T>(path: string, stepUp?: string) =>
    request<T>("DELETE", path, undefined, stepUp),
};

/** Currency and locale come from the jurisdiction pack, not from a hard-coded
 *  country. `configureLocale` is called once on sign-in; until it runs these
 *  defaults keep formatting sane rather than throwing. */
let locale = "en-ZW";
let currencySymbol = "$";
let currencyDecimals = 2;

export function configureLocale(opts: { locale?: string; symbol?: string; decimals?: number }) {
  if (opts.locale) locale = opts.locale;
  if (opts.symbol) currencySymbol = opts.symbol;
  if (opts.decimals !== undefined) currencyDecimals = opts.decimals;
}

export function currentCurrency() {
  return { locale, symbol: currencySymbol, decimals: currencyDecimals };
}

export function money(n: number | undefined | null, currency?: string) {
  const symbol = currency ?? currencySymbol;
  // Some locales are not present in every browser's ICU data; fall back rather
  // than let a formatting error take the page down.
  try {
    return `${symbol}${(n ?? 0).toLocaleString(locale, {
      minimumFractionDigits: currencyDecimals,
      maximumFractionDigits: currencyDecimals,
    })}`;
  } catch {
    return `${symbol}${(n ?? 0).toFixed(currencyDecimals)}`;
  }
}

function safeFormat(d: Date, opts: Intl.DateTimeFormatOptions, time = false) {
  try {
    return time ? d.toLocaleString(locale, opts) : d.toLocaleDateString(locale, opts);
  } catch {
    return time ? d.toISOString().slice(0, 16).replace("T", " ") : d.toISOString().slice(0, 10);
  }
}

export function fmtDate(s?: string | null) {
  if (!s) return "—";
  return safeFormat(new Date(s), { year: "numeric", month: "short", day: "numeric" });
}

export function fmtDateTime(s?: string | null) {
  if (!s) return "—";
  return safeFormat(new Date(s), {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }, true);
}

/** Hover-to-prefetch.
 *
 *  Two things make a click feel free, and both have to happen before it lands:
 *  the route's code chunk, and the data that page will ask for. Hovering a row
 *  starts both, so by the time the pointer arrives the work is usually done.
 *
 *  Deliberately fire-and-forget and deliberately capped. A prefetch that fails
 *  must be silent — the user has not asked for anything yet, and an error toast
 *  for a page somebody merely glanced at would be nonsense. The cache is a
 *  short-lived hint, not a store: stale data on a page somebody actually opens
 *  is worse than a fast one, so entries expire quickly and the real request
 *  still runs.
 */
const prefetched = new Map<string, number>();
const PREFETCH_TTL = 30_000;

export function prefetch(path: string) {
  const now = Date.now();
  const seen = prefetched.get(path);
  if (seen && now - seen < PREFETCH_TTL) return;
  prefetched.set(path, now);
  // Warm the HTTP cache. The page's own request will hit it.
  fetch(BASE + path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  }).catch(() => {
    // Silent by design: nobody asked for this yet.
    prefetched.delete(path);
  });
}

/** Warm the data a detail route will need, from the row that links to it. */
export function prefetchRoute(to: string) {
  const map: [RegExp, (id: string) => string][] = [
    [/^\/patients\/(\d+)$/, (id) => `/api/patients/${id}`],
    [/^\/products\/(\d+)$/, (id) => `/api/products/${id}`],
    [/^\/sales\/(\d+)$/, (id) => `/api/pos/sales/${id}`],
    [/^\/orders\/(\d+)$/, (id) => `/api/orders/${id}`],
  ];
  for (const [pattern, build] of map) {
    const hit = to.match(pattern);
    if (hit) {
      prefetch(build(hit[1]));
      return;
    }
  }
}
