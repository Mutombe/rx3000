/** Your account, and — if you administer this pharmacy — the pharmacy itself.
 *
 *  The two are on one page but kept visibly apart, because they carry different
 *  authority. Anyone may rename themselves or change their own password. The
 *  company details print on receipts and statutory returns, so only an
 *  administrator may edit them; everyone else sees them read-only, which is
 *  useful in its own right when you are covering an unfamiliar branch.
 *
 *  Whether the fields are editable is answered by the server, not inferred from
 *  the role string here. A permission the client decides is a permission the
 *  client can be wrong about.
 */
import { FormEvent, useEffect, useState } from "react";
import {
  Buildings,
  FloppyDisk,
  Key,
  Password,
  UserCircle,
} from "@phosphor-icons/react";
import { api, errorText  } from "../api";
import { useToast } from "../components/Toast";
import { Block } from "../components/Skeleton";
import PinInput from "../components/PinInput";

interface Me {
  id: number; username: string; full_name: string;
  role: string; active: boolean; can_edit_company: boolean;
}
interface CompanyField { key: string; label: string; value: string }

export default function Profile() {
  const [me, setMe] = useState<Me | null>(null);
  const [name, setName] = useState("");
  const [fields, setFields] = useState<CompanyField[] | null>(null);
  const [editable, setEditable] = useState(false);
  const [savingName, setSavingName] = useState(false);
  const [savingCompany, setSavingCompany] = useState(false);
  const [pw, setPw] = useState({ current_password: "", new_password: "", confirm: "" });
  const [newPin, setNewPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [pinPassword, setPinPassword] = useState("");
  const [pinBusy, setPinBusy] = useState(false);
  const [pinState, setPinState] = useState<{ pin_set: boolean } | null>(null);

  useEffect(() => {
    api.get<{ pin_set: boolean }>("/api/auth/pin").then(setPinState).catch(() => undefined);
  }, []);

  async function changePin(e: FormEvent) {
    e.preventDefault();
    if (newPin.length !== 4) { toast.error("A PIN is four digits."); return; }
    if (newPin !== confirmPin) { toast.error("The two PINs do not match."); return; }
    setPinBusy(true);
    try {
      await api.post("/api/auth/pin", { pin: newPin, password: pinPassword });
      toast.ok("Your till PIN is set.");
      setNewPin(""); setConfirmPin(""); setPinPassword("");
      setPinState({ pin_set: true });
    } catch (err) {
      toast.error(errorText(err, "That PIN could not be set."));
    } finally {
      setPinBusy(false);
    }
  }
  const toast = useToast();

  useEffect(() => {
    api.get<Me>("/api/profile/me")
      .then((m) => { setMe(m); setName(m.full_name); })
      .catch((e) => toast.error(errorText(e)));
    api.get<{ fields: CompanyField[]; editable: boolean }>("/api/profile/company")
      .then((c) => { setFields(c.fields); setEditable(c.editable); })
      .catch((e) => toast.error(errorText(e)));
  }, []);

  async function saveName(e: FormEvent) {
    e.preventDefault();
    setSavingName(true);
    try {
      const r = await api.put<{ message: string }>("/api/profile/me", { full_name: name });
      toast.ok(r.message);
    } catch (e: any) {
      toast.error(errorText(e));
    } finally {
      setSavingName(false);
    }
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    // Caught here rather than at the server: the two boxes disagreeing is a
    // typing slip, and a round trip to be told so is a round trip wasted.
    if (pw.new_password !== pw.confirm) {
      toast.error("The two new passwords do not match.");
      return;
    }
    try {
      const r = await api.post<{ message: string }>("/api/profile/password", {
        current_password: pw.current_password,
        new_password: pw.new_password,
      });
      toast.ok(r.message);
      setPw({ current_password: "", new_password: "", confirm: "" });
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  async function saveCompany(e: FormEvent) {
    e.preventDefault();
    if (!fields) return;
    setSavingCompany(true);
    try {
      const values = Object.fromEntries(fields.map((f) => [f.key, f.value]));
      const r = await api.put<{ message: string }>("/api/profile/company", { values });
      toast.ok(r.message);
    } catch (e: any) {
      toast.error(errorText(e));
    } finally {
      setSavingCompany(false);
    }
  }

  return (
    <div className="page">
      {/* Static: known before any request, so it never waits. */}
      <header className="page-head">
        <div>
          <h1>Profile</h1>
          <p className="muted">Your account and the pharmacy you are signed in to.</p>
        </div>
      </header>

      <section className="card">
        <h3 className="card-title"><UserCircle size={18} /> Your details</h3>
        <form className="stack" onSubmit={saveName}>
          <div className="field-row">
            <label>
              Full name
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </label>
            <label>
              Username
              {/* Not editable: it is the identity every audit row is written
                  against, and renaming it would orphan that history. */}
              <input value={me?.username ?? ""} readOnly disabled />
            </label>
            <label>
              Role
              <input value={me?.role ?? ""} readOnly disabled style={{ textTransform: "capitalize" }} />
            </label>
          </div>
          <div>
            <button className="btn primary" disabled={savingName || !me}>
              <FloppyDisk size={16} /> {savingName ? "Saving…" : "Save name"}
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <h3 className="card-title"><Key size={18} /> Password</h3>
        <form className="stack" onSubmit={changePassword}>
          <div className="field-row">
            <label>
              Current password
              <input type="password" autoComplete="current-password" required
                value={pw.current_password}
                onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
            </label>
            <label>
              New password
              <input type="password" autoComplete="new-password" required minLength={8}
                value={pw.new_password}
                onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
            </label>
            <label>
              Repeat new password
              <input type="password" autoComplete="new-password" required minLength={8}
                value={pw.confirm}
                onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
            </label>
          </div>
          <p className="muted small">
            At least 8 characters. You must enter the current password, otherwise an
            unattended till would be a password reset for anyone who walked up to it.
          </p>
          <div><button className="btn">Change password</button></div>
        </form>
      </section>

      <section className="card">
        <h3 className="card-title"><Password size={18} /> Till PIN</h3>
        <form className="stack" onSubmit={changePin}>
          <p className="muted">
            Four digits, for the authorisation prompts and for unlocking a till
            that has gone quiet. It never signs you in: the password starts a
            session, the PIN says who is standing at a machine that is already
            signed in. On a shared counter that is the only honest way to record
            who did what.
          </p>
          <div className="pin-setup">
            <label className="lock-field">
              New PIN
              <PinInput value={newPin} onChange={setNewPin} autoFocus={false} />
            </label>
            <label className="lock-field">
              Repeat it
              <PinInput value={confirmPin} onChange={setConfirmPin} autoFocus={false} />
            </label>
            <label className="lock-field">
              Your password
              <input
                type="password" autoComplete="current-password"
                value={pinPassword}
                onChange={(e) => setPinPassword(e.target.value)}
              />
            </label>
          </div>
          <p className="muted small">
            {pinState?.pin_set
              ? "A PIN is already set. Entering a new one replaces it."
              : "No PIN is set yet, so the till will not lock and the authorisation prompts ask for your password."}
            {" "}Nobody else can set your PIN, not even an administrator: a code
            somebody else chose records the wrong person against an action.
          </p>
          <div>
            <button className="btn" disabled={pinBusy}>
              {pinBusy ? "Saving…" : pinState?.pin_set ? "Replace PIN" : "Set PIN"}
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <h3 className="card-title"><Buildings size={18} /> Company profile</h3>
        {!editable && fields && (
          <p className="alert warn">
            These details print on receipts and statutory returns, so only an
            administrator can change them. You can read them here.
          </p>
        )}
        <form className="stack" onSubmit={saveCompany}>
          <div className="field-grid">
            {fields
              ? fields.map((f, i) => (
                  <label key={f.key}>
                    {f.label}
                    <input
                      value={f.value}
                      disabled={!editable}
                      onChange={(e) => {
                        const next = [...fields];
                        next[i] = { ...f, value: e.target.value };
                        setFields(next);
                      }}
                    />
                  </label>
                ))
              // The labels are not known until the server names them, so these
              // ghost. The heading above does not.
              : Array.from({ length: 8 }).map((_, i) => (
                  <label key={i}>
                    <Block w="14ch" h={11} />
                    <Block h={38} round="md" />
                  </label>
                ))}
          </div>
          {editable && (
            <div>
              <button className="btn primary" disabled={savingCompany || !fields}>
                <FloppyDisk size={16} /> {savingCompany ? "Saving…" : "Save company profile"}
              </button>
            </div>
          )}
        </form>
      </section>
    </div>
  );
}
