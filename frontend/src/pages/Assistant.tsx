/** RX-Assistant, with room to work.
 *
 *  The same conversation as the dock in the corner, at full width, for the
 *  questions that want a diagram or a long answer rather than a route and a
 *  sentence. Somebody training on a quiet afternoon opens this; somebody
 *  mid-script uses the dock.
 *
 *  This replaced Pulse AI, which asked one question at a time against a fixed
 *  snapshot of six figures and could not be asked where anything was. The
 *  history of those conversations is kept and still readable.
 */
import { useEffect, useState, useSyncExternalStore } from "react";
import { Sparkle, NotePencil } from "@phosphor-icons/react";

import { api } from "../api";
import AssistantChat from "../components/AssistantChat";
import AiHistory from "../components/AiHistory";
import { clearThread, getThread, subscribeThread } from "../assistantThread";

interface Atlas {
  generated: string;
  screens: number;
  keys: number;
  models: { wayfinding: string; thinking: string };
}

export default function Assistant() {
  const [atlas, setAtlas] = useState<Atlas | null>(null);
  const [history, setHistory] = useState(false);

  const thread = useSyncExternalStore(subscribeThread, getThread, getThread);

  useEffect(() => {
    api.get<Atlas>("/api/ai/assistant/atlas").then(setAtlas).catch(() => setAtlas(null));
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>RX-Assistant</h1>
          <div className="sub">
            Where things are in RX5000, how they are done, and what the codes
            mean. It can draw you the steps and take you there.
          </div>
        </div>
        <div className="ax-page-acts">
          {/* The thread is kept now: across the dock, this page, a reload and
              a shift. So putting one down has to be something somebody does on
              purpose, not something that happens to them. */}
          {thread.length > 0 && (
            <button className="btn secondary" onClick={clearThread}>
              <NotePencil size={15} /> New conversation
            </button>
          )}
          <button className="btn secondary" onClick={() => setHistory(true)}>
            Past questions
          </button>
        </div>
      </div>

      <div className="card ax-page">
        <AssistantChat />
      </div>

      {/* What it actually knows, said plainly. An assistant that will not say
          where its answers come from is one nobody should believe, and the
          honest answer here is short: it has read the software, not the shop. */}
      {atlas && (
        <p className="muted small ax-knows">
          <Sparkle size={12} weight="fill" /> Reads a map of{" "}
          <b>{atlas.screens}</b> screens and <b>{atlas.keys}</b> keyboard
          shortcuts, rebuilt with the software. It knows what RX5000 does, not
          what your pharmacy has done: nothing here reads a patient or a sale.
        </p>
      )}

      {history && (
        <AiHistory
          open={history}
          onClose={() => setHistory(false)}
          onOpenEntry={() => setHistory(false)}
          reloadKey={0}
        />
      )}
    </>
  );
}
