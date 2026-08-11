# RX3000 device agent

A browser cannot open a serial port, send an ESC/POS pulse to a cash drawer, or
hold a socket to a card terminal. This small service runs on the till PC and
does those things on RX3000's behalf. The browser talks to it over `localhost`.

**It is optional.** With no agent running, RX3000 falls back to browser printing
and manual capture of the card slip — nothing breaks, the till is just less
automatic.

## Run it

```powershell
cd device-agent
python agent.py            # http://127.0.0.1:9110
```

No dependencies beyond the standard library, unless you use Windows raw
printing (`pip install pywin32`).

## Configure

Set as environment variables before starting.

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_ENV` | `development` | Set to `production` on a real till — every simulator then refuses to act |
| `AGENT_PORT` | `9110` | Port the agent listens on |
| `AGENT_ORIGINS` | `http://localhost:5180,http://127.0.0.1:5180` | Which origins may call it |
| `PRINTER_PORT` | *(unset)* | `COM3`, `/dev/usb/lp0`, or a Windows printer share name |
| `PRINTER_MODE` | auto | `file` (COM/device node) or `windows` (raw queue) |
| `PRINTER_WIDTH` | `42` | Characters per line — 42 for 80mm, 32 for 58mm |
| `DRAWER_PIN` | `2` | RJ11 pin the drawer solenoid sits on (2 or 5) |
| `TERMINAL_DRIVER` | `simulator` | `simulator`, `tcp` or `none` |
| `TERMINAL_ID` | `SIM0001` | Terminal identifier stamped on the sale |
| `TERMINAL_HOST` / `TERMINAL_PORT` | — | Address of a semi-integrated terminal |
| `MOBILE_MONEY_DRIVER` | `none` | `simulator`, `paynow` or `none` |
| `PAYNOW_INTEGRATION_ID` / `PAYNOW_INTEGRATION_KEY` | — | Issued per merchant by Paynow |
| `PAYNOW_AUTH_EMAIL` | — | Required by Paynow on mobile transactions |
| `MOBILE_SIM_SECONDS` | `6` | How long the simulated customer takes to approve |
| `BIOMETRIC_DRIVER` | `none` | `simulator`, `health263` or `none` |
| `BIOMETRIC_MIN_QUALITY` | `60` | Below this the image is retaken, not submitted |
| `BIOMETRIC_DEVICE_ID` | — | Identifier of the reader issued to this till |

Example for a real till:

```powershell
$env:PRINTER_PORT = "COM3"
$env:TERMINAL_DRIVER = "tcp"
$env:TERMINAL_HOST = "192.168.1.50"
$env:TERMINAL_PORT = "5000"
python agent.py
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | What hardware is configured and reachable |
| POST | `/print` | Raw ESC/POS receipt, silent — no print dialog |
| POST | `/drawer/kick` | Open the cash drawer |
| POST | `/terminal/payment` | Take a card payment, return the slip detail |
| POST | `/terminal/cancel` | Cancel an in-flight terminal request |
| POST | `/mobile/initiate` | Push a mobile money request to a handset |
| POST | `/mobile/poll` | Check whether the customer has approved it |
| POST | `/biometric/capture` | One fingerprint impression, for verifying a member |
| POST | `/biometric/enrol` | The several impressions an enrolment needs |

The agent holds no credentials and never contacts the RX3000 server — the
browser is its only client.

## Adding a real card terminal

Every acquirer speaks its own protocol, so `drivers.py` defines a
`TerminalDriver` interface and the acquirer-specific part is one class.

`payment(amount, reference)` blocks until the terminal has an answer and returns:

```python
{
  "approved":    True,
  "auth_code":   "A1B2C3",       # acquirer approval code
  "reference":   "675659264258", # acquirer transaction reference / RRN
  "last4":       "4468",
  "scheme":      "visa",
  "terminal_id": "TILL01",
  "batch":       "20260806",     # settlement batch
  "message":     "APPROVED",
}
```

Those fields land on the sale and are what Card Reconciliation matches against
the settlement file. `TcpTerminal` is a skeleton for the common
semi-integrated shape — fill in the request/response framing from your
acquirer's integration guide and nothing else has to change.

**`simulator` is the default so the whole flow can be built and tested without
hardware.** It approves everything except amounts ending in `.13`, which
decline, so the failure path can be exercised deliberately. Set
`TERMINAL_DRIVER` explicitly on a real till.

## Adding mobile money

Mobile money is **not** a card terminal with a different logo. A card payment is
synchronous — send an amount, block until the terminal answers. A mobile money
payment is a *push*: the customer gets a prompt, wanders off to find their PIN,
and may never complete it. So the driver is two calls, not one.

```
initiate(amount, phone, method)  ->  { started, poll_ref, message }
poll(poll_ref)                   ->  { state: pending|paid|cancelled|failed, reference }
```

The till polls until it resolves or the provider's timeout expires. A dropped
poll is treated as still-pending rather than a failure, so a flaky connection
does not lose a payment that actually went through.

`SimulatorMobileMoney` models this rhythm without a provider account — phone
numbers ending `00` are cancelled by the "customer" and ending `99` fail, so
both unhappy paths can be exercised deliberately.

**`PaynowDriver` is not implemented.** Paynow (EcoCash, OneMoney and card behind
one API) publishes an integration guide; the field names, hash construction and
status vocabulary must come from it rather than be guessed at. Everything around
it — push, poll, timeout, cancellation, and landing the result as a
`mobile_money` tender carrying the provider reference — is built and proven
against the simulator.

## Fingerprint readers

Health 263 supplies the reader as physical hardware under the HSP contract and
retains ownership of it, so it lives here with the printer and the drawer rather
than anywhere in RX3000.

**A template never rests on this machine.** The matching happens at the switch,
against the funder's own enrolment. A capture is read from the sensor, handed to
the caller, and forgotten — nothing writes a template to disk or to the log, and
the gateway redacts it before the transaction is recorded. A fingerprint is
biometric personal data under the Cyber and Data Protection Act, and an audit
table quietly accumulating templates would turn a useful record into a liability.

An image scoring below `BIOMETRIC_MIN_QUALITY` is refused with `422` and no
template at all, because a poor scan sent to a switch comes back as a failed
match — which reads to the cashier as an accusation rather than as "wipe the
sensor".

To wire up the real reader, implement `Health263Reader` in `biometric.py`. It
needs the device model and its capture SDK. Everything around it — quality
gating, enrolment's repeated impressions, the transport into eligibility and
claims, the redaction, and the gateway's refusal to claim against a biometric
funder without a print — is already built and proven against the simulator.

## Before a till goes live

Set `AGENT_ENV=production`. Every simulator in this agent then refuses to act
and says what to configure instead. This matters more than it looks: a simulated
card terminal *approves* payments, and a simulated fingerprint reader *matches*
members. A till that went live with either would hand over goods against money
nobody paid and identities nobody proved, and would look completely normal doing
it. The refusal is deliberate — an unconfigured till should stop, not improvise.

The backend has the same switch: `RX3000_ENV=production`, and
`GET /api/integrations` reports what is still simulated or blocked.
