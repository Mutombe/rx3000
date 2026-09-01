/** A very small IndexedDB wrapper, for the things a till needs when the line is down.
 *
 *  IndexedDB rather than localStorage for two reasons that both matter here: a
 *  pharmacy's catalogue is thousands of products and localStorage caps out
 *  around five megabytes, and localStorage is synchronous — writing the whole
 *  catalogue would freeze the till mid-scan.
 *
 *  No library. What is needed is get, put, getAll and delete over two stores,
 *  and a dependency for that would cost more than it saves.
 */

//  Deliberately still "rx3000-offline" after the rename to RX5000. This database
//  holds sales a till took while the line was down and has not posted yet.
//  Opening a differently-named database does not migrate anything — it creates a
//  new empty one, and the queued sales are still on disk but unreachable by any
//  code that looks. A pharmacy would find that out as missing takings. The name
//  is invisible to everyone except a developer with devtools open; leaving it is
//  free, and changing it costs real money the first time it happens.
const DB_NAME = "rx3000-offline";
const DB_VERSION = 1;

/** Products, keyed by id. The catalogue as of the last successful sync. */
export const STORE_PRODUCTS = "products";
/** Sales taken while offline, waiting to be posted. */
export const STORE_QUEUE = "queue";
/** Small values: when the catalogue was last refreshed, and so on. */
export const STORE_META = "meta";

let dbPromise: Promise<IDBDatabase> | null = null;

function open(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("This browser has no local storage for offline use."));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_PRODUCTS)) {
        const store = db.createObjectStore(STORE_PRODUCTS, { keyPath: "id" });
        // Barcode lookup is the whole point of the cache at a till, so it gets
        // an index rather than a scan over every product.
        store.createIndex("barcode", "barcode", { unique: false });
      }
      if (!db.objectStoreNames.contains(STORE_QUEUE)) {
        // Keyed by the client-generated reference, which is also what makes a
        // replayed sale safe — see queue.ts.
        db.createObjectStore(STORE_QUEUE, { keyPath: "ref" });
      }
      if (!db.objectStoreNames.contains(STORE_META)) {
        db.createObjectStore(STORE_META, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Local storage could not be opened."));
  });
  return dbPromise;
}

function run<T>(
  store: string,
  mode: IDBTransactionMode,
  work: (s: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const tx = db.transaction(store, mode);
        const request = work(tx.objectStore(store));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        // A transaction can abort after the request succeeded — quota, for
        // instance, and the write is then not there despite having looked fine.
        tx.onabort = () => reject(tx.error ?? new Error("The local write was rolled back."));
      }),
  );
}

export const local = {
  get: <T>(store: string, key: IDBValidKey) => run<T>(store, "readonly", (s) => s.get(key) as IDBRequest<T>),
  all: <T>(store: string) => run<T[]>(store, "readonly", (s) => s.getAll() as IDBRequest<T[]>),
  put: <T>(store: string, value: T) => run(store, "readwrite", (s) => s.put(value as any)),
  del: (store: string, key: IDBValidKey) => run(store, "readwrite", (s) => s.delete(key)),
  count: (store: string) => run<number>(store, "readonly", (s) => s.count()),

  /** Replace a store's contents wholesale, in one transaction.
   *
   *  One transaction rather than a clear followed by many writes: if the tab is
   *  closed halfway through the latter, the till comes back with a catalogue
   *  that is missing half its products and no sign anything went wrong.
   */
  replaceAll: async <T>(store: string, values: T[]) => {
    const db = await open();
    return new Promise<void>((resolve, reject) => {
      const tx = db.transaction(store, "readwrite");
      const s = tx.objectStore(store);
      s.clear();
      values.forEach((v) => s.put(v as any));
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error ?? new Error("The catalogue write was rolled back."));
    });
  },
};

export async function meta<T>(key: string): Promise<T | undefined> {
  const row = await local.get<{ key: string; value: T }>(STORE_META, key);
  return row?.value;
}

export function setMeta<T>(key: string, value: T) {
  return local.put(STORE_META, { key, value });
}
