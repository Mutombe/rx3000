/** The way into the product, for four different people.
 *
 *  It is one screen because they arrive at the same URL, and one screen with
 *  three panels rather than three routes because the person who came to sign in
 *  and could not is the same person who then needs the reset, and a page load
 *  between those two is where somebody gives up and telephones the pharmacy.
 *
 *    - **Staff signing in.** The common case, so it is the panel that opens and
 *      the field that takes focus.
 *    - **Staff who have forgotten a password.** Answered with the till PIN,
 *      which every one of them already has and which is already rate limited.
 *      There is no email address on a user in this product and there should not
 *      be: it runs on a pharmacy own machines, often with no mail server at all.
 *    - **A prospect who wants to look.** Four hours, no password, no call.
 *    - **Somebody who landed here by mistake**, who wants the way back out.
 */
import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, Eye, EyeSlash, GraduationCap, Storefront } from "@phosphor-icons/react";
import { api, errorText, setToken } from "../api";
import PinInput from "../components/PinInput";
import { User } from "../types";

type Panel = "signin" | "reset" | "demo";

interface Auth { access_token: string; user: User }

export default function Login() {
  const [panel, setPanel] = useState<Panel>("signin");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /** Why the last session ended, if it did.
   *
   *  A 401 redirects here, and the redirect is a page load, which destroys any
   *  toast raised alongside it. So the reason is handed over in session storage
   *  and shown on the screen the person actually lands on, rather than flashing
   *  on the one they are leaving. */
  const [signedOut, setSignedOut] = useState("");
  useEffect(() => {
    try {
      const why = sessionStorage.getItem("rx5000_signed_out");
      if (why) {
        setSignedOut(why);
        sessionStorage.removeItem("rx5000_signed_out");
      }
    } catch { /* private mode: nothing to show, which is fine */ }
  }, []);

  // Reset panel
  const [pin, setPin] = useState("");
  const [newPassword, setNewPassword] = useState("");

  // Demo panel
  const [demoName, setDemoName] = useState("");
  const [demoHours, setDemoHours] = useState(4);

  const navigate = useNavigate();
  const location = useLocation();

  /* A demo that ran out sends the operator back here. Saying so is the whole
     point: without it the screen looks like an ordinary sign-in, and the last
     thing the product does is appear to have forgotten them. */
  const endedDemo = (location.state as { demoEnded?: boolean } | null)?.demoEnded;

  useEffect(() => {
    // The length of a demo is decided by the server. Quoting a number the
    // frontend invented is how "two hours" ends up written in six files and
    // wrong in four of them.
    api.get<{ hours: number }>("/api/auth/demo/length")
      .then((d) => setDemoHours(d.hours))
      .catch(() => { /* the default in state is the same number */ });
  }, []);

  function land(res: Auth) {
    setToken(res.access_token);
    navigate("/");
  }

  async function submitSignIn(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      land(await api.post<Auth>("/api/auth/login", { username, password }));
    } catch (err) {
      setError(errorText(err, "That username and password were not accepted."));
    } finally { setBusy(false); }
  }

  async function submitReset(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      land(await api.post<Auth>("/api/auth/reset-with-pin", {
        username, pin, new_password: newPassword,
      }));
    } catch (err) {
      setError(errorText(err, "That username and PIN were not accepted."));
      setPin("");
    } finally { setBusy(false); }
  }

  async function submitDemo(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      land(await api.post<Auth>("/api/auth/demo", { full_name: demoName }));
    } catch (err) {
      setError(errorText(err, "The demo could not be started just now."));
    } finally { setBusy(false); }
  }

  function go(next: Panel) {
    setPanel(next); setError(""); setPassword(""); setPin(""); setNewPassword("");
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="brand-lg">
          <span className="brand-lockup" role="img"
                aria-label="RX5000, pharmacy operating system" />
        </div>
        <p className="tag">Pharmacy management, dispensing and point of sale</p>

        {/* Everything between the wordmark and the footer lives in here, and it
            is centred in whatever room is left over. All three panels share one
            card height, so the shortest of them has real slack; split evenly
            above and below it that reads as composition, and dumped underneath
            it reads as a rendering fault. */}
        <div className="login-body">
        {endedDemo && (
          <div className="login-note">
            <b>Your demo has ended.</b> Nothing you entered was thrown away. Ask us
            for an account and you carry on from exactly where you stopped.
          </div>
        )}
        {signedOut && !error && <div className="alert">{signedOut}</div>}
        {error && <div className="error-banner">{error}</div>}

        {panel === "signin" && (
          <form onSubmit={submitSignIn}>
            <div className="field">
              <label htmlFor="lg-user">Username</label>
              <input id="lg-user" value={username} autoFocus autoComplete="username"
                     onChange={(e) => setUsername(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lg-pass">Password</label>
              {/* The eye is inside the field rather than beside it, because a
                  password box people cannot read is where most failed sign-ins
                  on a counter keyboard come from. */}
              <div className="pw">
                <input
                  id="lg-pass"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  className="pw-eye"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-pressed={showPassword}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  data-tip={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeSlash size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
            <button className="login-go" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
            <button type="button" className="link-btn" onClick={() => go("reset")}>
              I have forgotten my password
            </button>
          </form>
        )}

        {panel === "reset" && (
          <form onSubmit={submitReset}>
            <p className="login-lead">
              Your till PIN sets a new password.
            </p>
            <div className="field">
              <label htmlFor="rs-user">Username</label>
              <input id="rs-user" value={username} autoFocus autoComplete="username"
                     onChange={(e) => setUsername(e.target.value)} />
            </div>
            <div className="field">
              <label>Till PIN</label>
              <PinInput value={pin} onChange={(v) => { setPin(v); setError(""); }} disabled={busy} />
            </div>
            <div className="field">
              <label htmlFor="rs-new">New password</label>
              <div className="pw">
                <input
                  id="rs-new"
                  type={showPassword ? "text" : "password"}
                  value={newPassword}
                  autoComplete="new-password"
                  onChange={(e) => setNewPassword(e.target.value)}
                />
                <button type="button" className="pw-eye"
                        onClick={() => setShowPassword((v) => !v)}
                        aria-pressed={showPassword}
                        aria-label={showPassword ? "Hide password" : "Show password"}>
                  {showPassword ? <EyeSlash size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
            <button className="login-go" disabled={busy || pin.length < 4 || !newPassword}>
              {busy ? "Setting it…" : "Set password and sign in"}
            </button>
            <button type="button" className="link-btn" onClick={() => go("signin")}>
              <ArrowLeft size={13} /> Back to sign in
            </button>
          </form>
        )}

        {panel === "demo" && (
          <form onSubmit={submitDemo}>
            <p className="login-lead">
              A full account for {demoHours} hours. Nothing switched off.
            </p>
            <div className="field">
              <label htmlFor="dm-name">Your name</label>
              <input id="dm-name" value={demoName} autoFocus placeholder="Tendai Moyo"
                     onChange={(e) => setDemoName(e.target.value)} />
            </div>
            <button className="login-go" disabled={busy}>
              {busy ? "Setting it up…" : `Start the ${demoHours} hour demo`}
            </button>
            <p className="login-small">
              When the time is up the account stops and your work is kept.
            </p>
            <button type="button" className="link-btn" onClick={() => go("signin")}>
              <ArrowLeft size={13} /> Back to sign in
            </button>
          </form>
        )}

        {panel === "signin" && (
          <div className="login-alts">
            <button type="button" className="alt-card" onClick={() => go("demo")}>
              <b>Try it for {demoHours} hours</b>
              <span>No password, nothing switched off</span>
            </button>
          </div>
        )}

        </div>

        <div className="login-foot login-push">
          <Link to="/welcome"><Storefront size={14} /> What RX5000 does</Link>
          <Link to="/training"><GraduationCap size={14} /> Training material</Link>
        </div>

        {panel === "signin" && (
          <p className="demo-creds">
            <b>admin</b>/admin123 · <b>pharmacist</b>/pharm123 · <b>cashier</b>/cash123
          </p>
        )}
      </div>
    </div>
  );
}
