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
      const raw = typeof d?.msg === "string" ? d.msg : "is not valid";
      // Pydantic writes for a developer: "Field required", "Input should be a
      // valid integer". A person filling in a form needs the field named the
      // way it is labelled on screen, and the requirement in plain words.
      const msg = raw
        .replace(/^Field required$/i, "is required")
        .replace(/^Input should be /i, "should be ")
        .replace(/^Value error, /i, "")
        .replace(/^String should have at least (\d+) characters?$/i, "cannot be empty")
        .replace(/^ensure this value /i, "must ");
      const field = loc
        .replace(/_/g, " ")
        .replace(/\bid\b/gi, "")
        .trim();
      const label = field ? field.charAt(0).toUpperCase() + field.slice(1) : "";
      return label ? `${label} ${msg}`.replace(/\s+/g, " ").trim() : msg;
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

/** Details that a framework produced rather than a person.
 *
 *  FastAPI answers an unknown address with `{"detail": "Not Found"}`. That is
 *  technically a message and practically none: it beat the carefully worded
 *  fallback simply by existing, so a missing endpoint told a pharmacist "Not
 *  Found" and left them looking for a record that was never the problem.
 *  Anything on this list is treated as though the server said nothing.
 */
const EMPTY_DETAILS = new Set([
  "not found", "method not allowed", "internal server error",
  "unprocessable entity", "bad request", "forbidden", "unauthorized",
  "conflict", "error", "failed",
]);

function isUseless(detail: string): boolean {
  return EMPTY_DETAILS.has(detail.trim().toLowerCase().replace(/[.!]$/, ""));
}

/** A sentence for a response that did not explain itself.
 *
 *  `path` matters more than it looks. A 404 means two completely different
 *  things: a record that has been deleted, and an address that does not exist
 *  because the front end is asking for the wrong one. Telling a pharmacist
 *  "that record no longer exists" when the truth is that we shipped a typo
 *  sends them looking for a data problem they will never find — which is
 *  exactly what happened with the switch log, where the URL was missing its
 *  /api prefix and the screen blamed the data.
 *
 *  The heuristic is deliberately simple: an address ending in a collection
 *  (no trailing identifier) cannot have had "the record" deleted, so a 404
 *  there is a fault in the software rather than in the data.
 */
function statusWording(status: number, path = ""): string {
  if (status === 400) return "That request was not valid. Check the values and try again.";
  if (status === 403) return "You do not have permission to do that.";
  if (status === 404) {
    const tail = path.split("?")[0].replace(/\/+$/, "").split("/").pop() ?? "";
    const looksLikeARecord = /^\d+$/.test(tail);
    return looksLikeARecord
      ? "That record no longer exists."
      : "That part of the system could not be reached. This is a fault on our "
        + "side rather than anything you did — please report it.";
  }
  if (status === 405) {
    return "That action is not allowed here. This is a fault on our side; please report it.";
  }
  if (status === 409) return "Someone else changed this first. Reload and try again.";
  if (status === 413) return "That file is too large to upload.";
  if (status === 422) return "Some of the details were not accepted. Check the highlighted fields.";
  if (status === 429) return "Too many requests just now. Wait a moment and retry.";
  if (status === 502 || status === 503 || status === 504)
    return "The server is not responding. It may be starting up — try again shortly.";
  if (status >= 500) return "Something went wrong at the server. Please try again.";
  return `The request was refused (${status}).`;
}

/** Put the technical detail where a developer will find it, and nowhere else.
 *
 *  The person at the counter needs one sentence they can act on. Everything
 *  that helps diagnose the fault — the method, the address, the status, the
 *  raw body — belongs in the console, where it is available when someone goes
 *  looking and invisible when they are serving a customer. Putting either one
 *  in the other's place is how you end up with a stack trace in a toast, or a
 *  bug report that says only "it did not work".
 */
function logFailure(
  method: string, path: string, status: number, raw: unknown, shown: string,
) {
  // One console.error, not a group. A collapsed group is not reliably captured
  // by tooling that watches the console, and a diagnostic nobody can capture is
  // only half a diagnostic.
  console.error(
    `[RX3000] ${method} ${path} -> ${status}`,
    { status, method, path, serverSaid: raw, shownToUser: shown },
  );
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
  let res: Response;
  try {
    res = await fetch(BASE + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(stepUp ? { "X-Step-Up": stepUp } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    // fetch rejects for exactly one class of reason: the request never got an
    // answer. "TypeError: Failed to fetch" is what the browser calls that, and
    // it is meaningless to anybody standing at a till.
    logFailure(method, path, 0, String(cause), "Could not reach the server.");
    throw new ApiError(
      0,
      "Could not reach the server. Check the connection, or the server may be down.",
    );
  }
  if (res.status === 401) {
    setToken(null);
    window.location.href = "/login";
    throw new ApiError(401, "Your session has ended. Please sign in again.");
  }
  if (!res.ok) {
    let detail = "";
    let raw: unknown;
    try {
      raw = await res.json();
      detail = readableDetail((raw as any)?.detail) ?? "";
    } catch {
      /* body was not JSON — the status-based wording carries it instead */
    }
    // Never throw a blank message. HTTP/2 carries no status text, so
    // `res.statusText` is an empty string on any modern host — which produced a
    // toast with a count badge and no words at all. An error nobody can read is
    // worse than no error: it says something is wrong and refuses to say what.
    const clean = detail.trim();
    const shown = clean && !isUseless(clean) ? clean : statusWording(res.status, path);
    logFailure(method, path, res.status, raw, shown);
    throw new ApiError(res.status, shown);
  }

  // A 204, or any empty body, is a success with nothing to parse. Calling
  // res.json() on it throws, and the caller then reports a working request as
  // a failure.
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    logFailure(method, path, res.status, text.slice(0, 400),
               "The server sent something we could not read.");
    throw new ApiError(res.status, "The server sent something we could not read.");
  }
}

/** The sentence to show a person for any thrown thing.
 *
 *  Requests already fail with a message written for a human. This exists for
 *  everything else: a bug in our own code throws a TypeError whose message is
 *  written for a compiler, and "Cannot read properties of undefined" in a toast
 *  tells a pharmacist nothing except that we are not in control of the
 *  software. Those go to the console, where they are useful, and the screen
 *  gets one honest sentence.
 */
export function errorText(cause: unknown, fallback = "That did not work. Please try again."): string {
  if (cause instanceof ApiError) return cause.message;
  if (typeof cause === "string" && cause.trim()) return cause;
  // Anything else is ours, and is a defect rather than a condition.
  console.error("[RX3000] unhandled failure:", cause);
  return fallback;
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
  /** Fetch a file, with the session's credentials attached.
   *
   *  A plain `<a href>` or a `window.location` cannot carry the Authorization
   *  header, and the usual workaround — putting the token in the query string —
   *  writes it into every access log, proxy log and browser history it passes
   *  through. So a download is a normal authenticated fetch that happens to
   *  return bytes, and the filename is read back off the response rather than
   *  guessed at.
   */
  blob: async (path: string): Promise<{ body: Blob; filename: string }> => {
    const res = await fetch(BASE + path, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      // An error body here is JSON, not a file, and it usually contains the
      // one sentence explaining what was wrong with the parameters.
      let detail = statusWording(res.status);
      try {
        detail = readableDetail(await res.json()) || detail;
      } catch {
        /* not JSON; the status wording stands */
      }
      throw new Error(detail);
    }
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
    return {
      body: await res.blob(),
      filename: match ? decodeURIComponent(match[1]) : "",
    };
  },
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
