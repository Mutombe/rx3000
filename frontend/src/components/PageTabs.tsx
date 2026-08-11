/** Horizontal page tabs with URL deep-linking.
 *
 *  Every screen shows exactly one dataset at a time. The active tab lives in
 *  `?tab=`, so a view can be linked, bookmarked and reloaded — and the browser
 *  back button steps through tabs the way users expect.
 */
import { useSearchParams } from "react-router-dom";

export type TabDef<T extends string> = {
  key: T;
  label: string;
  /** Optional record count rendered as a chip on the tab. */
  count?: number;
  hint?: string;
};

export function usePageTabs<T extends string>(tabs: TabDef<T>[], fallback: T) {
  const [params, setParams] = useSearchParams();
  const tab = (tabs.some((t) => t.key === params.get("tab")) ? params.get("tab") : fallback) as T;

  function setTab(next: T) {
    const q = new URLSearchParams(params);
    if (next === fallback) q.delete("tab");
    else q.set("tab", next);
    setParams(q, { replace: true });
  }

  return [tab, setTab] as const;
}

export default function PageTabs<T extends string>({ tabs, tab, setTab }: {
  tabs: TabDef<T>[];
  tab: T;
  setTab: (t: T) => void;
}) {
  return (
    <div className="pill-tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={tab === t.key}
          title={t.hint}
          className={tab === t.key ? "active" : ""}
          onClick={() => setTab(t.key)}
        >
          {t.label}
          {t.count !== undefined && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}
