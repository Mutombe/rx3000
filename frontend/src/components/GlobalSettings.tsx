/** The settings screen: what each figure does, and what it is currently set to.
 *
 *  Built from the server's declaration rather than hand-written, so a setting
 *  added in the backend appears here without anybody remembering to add it. A
 *  hand-built settings form drifts from the settings that exist, and the fields
 *  that go missing are the ones added last — which are the ones nobody has
 *  reviewed.
 *
 *  Each row leads with the effect rather than the label. "Minimum lay-by
 *  deposit: 20%" tells somebody nothing about what happens if they set it to
 *  zero, and the person most likely to set it to zero is the one who has just
 *  lost an argument at the counter.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { useStepUp, CANCELLED } from "./StepUp";
import { TableSkeleton } from "./Skeleton";
import { useToast } from "./Toast";

interface Row {
  key: string; label: string; kind: string; unit: string; effect: string;
  value: string | number | boolean; default: string | number | boolean;
  is_set: boolean;
}
interface Payload { groups: Record<string, Row[]>; unrecognised: string[] }

export default function GlobalSettings() {
  const toast = useToast();
  const [data, setData] = useState<Payload | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const { guarded, prompt } = useStepUp();
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    api.get<Payload>("/api/settings")
      .then((p) => { setData(p); setDraft({}); })
      .catch((e) => toast.error(errorText(e, "Settings could not be loaded.")));
  }, [toast]);

  useEffect(load, [load]);

  async function save(key: string) {
    const value = draft[key];
    if (value === undefined) return;
    setBusy(key);
    try {
      // `guarded` deals with the password entirely: it tries the save, and only
      // if the server answers 428 does it raise the prompt and retry with the
      // token. The alternative — this screen deciding for itself when authority
      // is needed — duplicates a rule the server already owns, and drifts from
      // it the moment the rule changes.
      //
      // PUT, because the endpoint is a PUT. A POST here returned 405 and the
      // screen reported it as a failed save.
      const res = await guarded(
        "settings.global",
        (token) => api.put<{ message: string }>(
          `/api/settings/${key}`, { value }, token,
        ),
        key,
      );
      if (res === CANCELLED) return;  // still on the old value; say nothing
      toast.ok(res.message);
      load();
    } catch (e: any) {
      toast.error(errorText(e, "That setting could not be saved."));
    } finally {
      setBusy("");
    }
  }

  if (!data) return <div className="card"><TableSkeleton cols={2} rows={8} /></div>;

  function render(row: Row) {
    const current = draft[row.key] ?? String(row.value);
    const dirty = draft[row.key] !== undefined && draft[row.key] !== String(row.value);

    return (
      <div key={row.key} className="gs-row">
        <div className="gs-main">
          <label className="gs-label" htmlFor={row.key}>
            {row.label}
            {/* A value somebody chose reads differently from one that merely
                matches the default — that is the difference between reviewed
                and never looked at. */}
            {!row.is_set && <span className="gs-flag">not set</span>}
          </label>
          <p className="gs-effect">{row.effect}</p>
        </div>

        <div className="gs-control">
          {row.kind === "bool" ? (
            <select
              id={row.key}
              value={current === "true" || current === "1" ? "true" : "false"}
              onChange={(e) => setDraft((d) => ({ ...d, [row.key]: e.target.value }))}
            >
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          ) : (
            <div className="gs-input">
              <input
                id={row.key}
                type={row.kind === "text" ? "text" : "number"}
                step={row.kind === "money" ? "0.01" : "1"}
                value={current}
                onChange={(e) => setDraft((d) => ({ ...d, [row.key]: e.target.value }))}
                onKeyDown={(e) => { if (e.key === "Enter") save(row.key); }}
              />
              {row.unit && <span className="gs-unit">{row.unit}</span>}
            </div>
          )}
          <button
            className="btn small"
            disabled={!dirty || busy === row.key}
            onClick={() => save(row.key)}
          >
            {busy === row.key ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      {prompt}

      {data.unrecognised.length > 0 && (
        // Surfaced, not hidden. A stray key is almost always a typo that has
        // been quietly doing nothing since somebody set it.
        <p className="st-note is-bad">
          {data.unrecognised.length} stored setting(s) are not recognised by this
          version and are being ignored: {data.unrecognised.join(", ")}.
        </p>
      )}

      {Object.entries(data.groups).map(([group, rows]) => (
        <div className="card" key={group}>
          <h3>{group}</h3>
          <div className="gs-list">{rows.map(render)}</div>
        </div>
      ))}
    </>
  );
}
