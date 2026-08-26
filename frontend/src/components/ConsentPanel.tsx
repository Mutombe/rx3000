/** What this person has actually agreed to, and the evidence for it.
 *
 *  A tick box answers "may we message them" and nothing else. It cannot answer
 *  when they agreed, what they were told, through which channel, who recorded
 *  it, or whether they have since said stop — and those are the questions asked
 *  when somebody complains, which is the only occasion the answer matters.
 *
 *  So this shows the answer per channel with its provenance beside it, in words.
 *  An imported flag reads "imported, provenance unknown" rather than as a tick,
 *  because a tick makes it look like the signed form next to it and it is not.
 *
 *  A withdrawal is recorded, never a deletion. Somebody agreeing and later
 *  changing their mind is two facts, and erasing the first leaves the pharmacy
 *  unable to say why it ever sent anything.
 */
import { useCallback, useEffect, useState } from "react";
import { Check, Prohibit } from "@phosphor-icons/react";
import { api, errorText, fmtDateTime } from "../api";
import BusyButton from "../components/BusyButton";
import Select from "./Select";
import { useToast } from "./Toast";

interface ChannelState {
  allowed: boolean;
  since: string | null;
  captured_via: string;
  how: string;
  evidence: string;
}

interface ConsentEvent {
  id: number;
  state: "granted" | "withdrawn";
  channel: string;
  captured_via: string;
  how: string;
  wording: string;
  note: string;
  by: string;
  created_at: string;
}

interface State {
  flag: boolean;
  channels: Record<string, ChannelState>;
  any_allowed: boolean;
  events: ConsentEvent[];
}

const CHANNELS = ["sms", "whatsapp", "email", "phone", "post"];
const CHANNEL_LABEL: Record<string, string> = {
  sms: "SMS", whatsapp: "WhatsApp", email: "Email", phone: "Telephone", post: "Post",
};
const CAPTURE = [
  { value: "counter", label: "Said so at the counter" },
  { value: "form", label: "Signed a form" },
  { value: "phone", label: "Said so on the telephone" },
  { value: "portal", label: "Through the patient portal" },
  { value: "reply", label: "Replied to a message" },
];

export default function ConsentPanel({
  subjectType, subjectId,
}: {
  subjectType: "patient" | "lead" | "contact";
  subjectId: number;
}) {
  const [state, setState] = useState<State | null>(null);
  const [failed, setFailed] = useState("");
  const [channel, setChannel] = useState("all");
  const [via, setVia] = useState("counter");
  const [note, setNote] = useState("");
  const toast = useToast();

  const load = useCallback(() =>
    api.get<State>(`/api/consent/${subjectType}/${subjectId}`)
      .then((s) => { setState(s); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "The consent record could not be read."))),
  [subjectType, subjectId]);

  useEffect(() => { load(); }, [load]);

  async function record(next: "granted" | "withdrawn") {
    try {
      await api.post(`/api/consent/${subjectType}/${subjectId}`,
                     { state: next, channel, captured_via: via, note });
      toast.ok(next === "granted" ? "Consent recorded." : "Withdrawal recorded.");
      setNote("");
      await load();
    } catch (e) {
      toast.error(errorText(e, "That could not be recorded."));
    }
  }

  if (failed) return <div className="alert error">{failed}</div>;
  if (!state) return <p className="muted">Reading the consent record…</p>;

  return (
    <div className="consent">
      <div className="consent-grid">
        {CHANNELS.map((c) => {
          const s = state.channels[c];
          return (
            <div key={c} className={`consent-cell${s?.allowed ? " is-on" : ""}`}>
              <b>
                {s?.allowed ? <Check size={13} weight="bold" /> : <Prohibit size={13} />}
                {CHANNEL_LABEL[c]}
              </b>
              {/* The provenance in words, beside the answer. A signed form and an
                  imported flag are not the same evidence and must not read the
                  same. */}
              <span className="muted">{s?.evidence ?? "no record"}</span>
              {s?.since && <span className="muted">{fmtDateTime(s.since)}</span>}
            </div>
          );
        })}
      </div>

      <div className="consent-record">
        <label className="field">
          Channel
          <Select value={channel} onChange={setChannel}
                  options={[{ value: "all", label: "Everything" },
                            ...CHANNELS.map((c) => ({ value: c, label: CHANNEL_LABEL[c] }))]} />
        </label>
        <label className="field">
          How was it given
          <Select value={via} onChange={setVia} options={CAPTURE} />
        </label>
        <label className="field">
          Note
          <input value={note} placeholder="anything worth remembering"
                 onChange={(e) => setNote(e.target.value)} />
        </label>
        <div className="consent-actions">
          <BusyButton className="btn small" onClick={() => record("granted")}>
            They agreed
          </BusyButton>
          <BusyButton className="btn small danger" onClick={() => record("withdrawn")}>
            They said stop
          </BusyButton>
        </div>
      </div>

      {state.events.length > 0 && (
        <details className="consent-history">
          <summary>{state.events.length} entr{state.events.length === 1 ? "y" : "ies"} on file</summary>
          <ul>
            {state.events.map((e) => (
              <li key={e.id}>
                <b>{e.state === "granted" ? "Agreed" : "Said stop"}</b>
                {e.channel !== "all" && <> to {CHANNEL_LABEL[e.channel] ?? e.channel}</>}
                {" · "}{e.how}
                {e.by && <> · recorded by {e.by}</>}
                <div className="muted small">{fmtDateTime(e.created_at)}</div>
                {e.note && <div className="muted small">{e.note}</div>}
                {/* Kept because consent to wording nobody retained is not
                    evidence of anything. */}
                {e.wording && <div className="consent-wording">“{e.wording}”</div>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
