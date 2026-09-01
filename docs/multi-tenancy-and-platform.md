# Running RX5000 for many pharmacies

Where this starts from, because it decides everything after it: **RX5000 is
single-tenant today.** One deployment is one pharmacy. `Branch` models a chain's
own branches, `Company` is a CRM customer record, and all 289 routes query
without any notion of who is asking. Drivers already exist as staff users
(`Delivery.driver_id`), prescribers already have portal credentials
(`Doctor.portal_password_hash`), and the Paynow integration is scaffolded and not
finished.

---

## 1. One database per pharmacy

**Recommendation: a schema per pharmacy on a shared Postgres cluster, plus one
small platform database that holds no patient data.**

The alternative — one shared schema with a `tenant_id` column on every table — is
cheaper to host and much more dangerous here, for a reason this codebase has
already demonstrated. A `tenant_id` model is only as good as the WHERE clause on
every query, and this week an audit found **52 endpoints that took a `limit` and
not one of them clamped it**. That is the same class of mistake: a rule that must
be remembered in every query will be forgotten in some of them. Forgetting a limit
returns too many rows; forgetting a tenant filter shows one pharmacy another
pharmacy's patients.

With a schema per pharmacy the connection decides what is visible, so a missed
filter cannot cross a tenant boundary — the rows are not in the database being
queried. That property is worth real money in hosting, because the failure it
prevents is the one that ends the business.

It also suits what pharmacies and regulators want:

- **Their data is theirs.** A per-tenant dump is a file. Leaving is a file, an
  audit is a file, a subpoena is a file.
- **Restores are per pharmacy.** Restoring one tenant does not roll back the rest.
- **A big chain can be moved** to its own cluster later without redesigning
  anything.
- **The desktop app already works this way**: a pharmacy running its own backend
  on the premises is a tenant of one.

What it costs, honestly:

- Migrations run per tenant. `run_migrations()` already does the work; it has to
  be called in a loop, and a failure on tenant 40 of 200 must be reported rather
  than swallowed.
- Cross-tenant questions ("how many scripts across all customers") need the
  platform database or a nightly roll-up. That is a real cost and worth paying.
- Connection pooling matters early. PgBouncer in transaction mode.

Rough shape:

    platform            tenants, plans, subscriptions, invoices, identities, grants
    tenant_greenwood    the whole RX5000 schema
    tenant_bulawayo     the whole RX5000 schema

Tenant resolution per request, in order: subdomain (greenwood.rx5000.co.zw), then
the tenant claim in the token. The app then runs exactly as it does now.

---

## 2. Who the platform is, and what it must never hold

A separate admin surface, on the platform database:

- tenants and their status (trial, active, suspended, closed)
- plans, subscriptions, invoices, payments
- usage counters for billing (scripts, tills, branches)
- feature flags per tenant
- **support access grants**: time-boxed, reason-required, and visible to the
  pharmacy in their own audit log

The rule that keeps this defensible: **the platform database holds no patient
data.** Not a name, not a script. Everything clinical stays in the tenant's own
schema. When support needs to look, they are granted temporary access into that
tenant, and the pharmacy can see that it happened.

---

## 3. Billing that cannot hurt a patient

Self-service via Paynow (EcoCash / OneMoney), already scaffolded and blocked on a
BillPay vendor account from support@paynow.co.zw — a commercial step, not an
engineering one.

One design rule matters more than the rest: **non-payment must never stop
dispensing.** A pharmacy that cannot hand a patient their medicine because of a
billing dispute is a safety problem and a reputational one. The ladder:

1. reminders, in-app and by message
2. read-only on the *business* surfaces — reports, exports, CRM
3. new-branch and new-user creation blocked
4. dispensing, the till, and the controlled register **always keep working**

Suspension takes away convenience, never care.

---

## 4. Drivers, and which pharmacy they belong to

Drivers are already staff users with deliveries assigned to them, so inside a
tenant nothing changes. The question is only how a driver's phone finds the right
tenant.

**A platform identity directory**: email to the tenant(s) that have invited that
person. A driver signs in once; if they work for two pharmacies they choose, and
the session is pinned to one tenant at a time. The alternative — asking a driver
to type a pharmacy code — works, and is a good fallback when the directory is
unreachable.

The driver app itself should be small and offline-tolerant: today's runs, proof of
delivery, a signature, and a queue that syncs when there is signal. It needs
almost none of RX5000, which is an argument for a separate lightweight app rather
than a role inside the main one.

---

## 5. Staff, prescribers, patients: three different kinds of access

The distinction that keeps this simple: **staff are inside the tenant; everyone
else is outside it looking through a narrow window.**

| Who | Sees | Mechanism |
|---|---|---|
| Pharmacy staff | the tenant's data, bounded by role | tenant login + role + step-up |
| Prescribers | only scripts they wrote, only their own patients | portal identity, scoped per record |
| Patients | only themselves | invited identity, scoped to one patient row |
| Drivers | only today's deliveries assigned to them | scoped session, no clinical detail |

**No, prescribers should not see the pharmacy's data.** They are not employees. A
doctor needs to write a script, see what happened to the ones they wrote, and
nothing else — not stock, not takings, not other doctors' patients. The portal
already exists for this, and it should stay deliberately thin.

---

## 6. Hosting

- Stateless API containers behind a load balancer; the tenant comes from the
  request, so any container can serve any pharmacy.
- One Postgres cluster with PgBouncer, until a tenant is big enough to deserve its
  own: the design allows moving one without touching the others.
- Backups: cluster-level point-in-time recovery, plus a per-tenant logical dump a
  pharmacy can be handed.
- The desktop app keeps working against a local backend for pharmacies with bad
  connectivity. Same code, deployed differently.

---

## 7. Onboarding a pharmacy in minutes

Because a tenant is a schema, provisioning is a script rather than a project:

1. create the schema
2. run `create_all` and `run_migrations()`
3. seed the jurisdiction pack (currencies, VAT, schedules, tariffs)
4. create the first admin and email the invitation
5. optionally import an opening product file — the price importer already reads
   NAPPI, barcode, cost, selling price, SEP, MMAP and the active ingredient

Steps 1 to 4 are seconds of work. Step 5 is what actually takes a pharmacy a day,
so the import is the thing to polish, and the sample file should be published.

---

## 8. Demos that cost nothing to give

The same machinery: a **template tenant** with realistic seeded data, cloned per
demo, handed out on a self-service link, and deleted automatically after a
fortnight. Sales stops needing an engineer, and every demo starts identical.

---

## 9. Attribution when the till is already logged in

The sharpest question of the set, because the situation described is not an edge
case — it is how a pharmacy actually works. A machine is logged in, and whoever is
standing there uses it.

The answer is to stop treating the session as the actor:

- **The session identifies the machine and the shift. The actor is recorded per
  action.** Anything attributable — dispensing, the controlled register, voids,
  refunds, price overrides, cash-up, stock adjustments — records who did *that*,
  not who logged in this morning.
- **A short idle lock, not a logout.** The screen locks after a few minutes; the
  shift, the basket and the open script survive. Logging out loses work, so staff
  turn it off, and then nothing is attributable at all.
- **A per-user PIN to unlock and to sign an action.** Four to six digits is enough
  to say who is standing there; the password stays for starting the session.
- The pharmacist's initial on a dispensing is this idea in miniature: the label
  carries who checked it, which is not necessarily who is logged in.

Two things to be honest about. A PIN is not a signature — it is deterrence and a
record, enough for "who dispensed this" and not enough for a court. And none of
this survives staff sharing PINs; the audit trail's job is to make that visible,
not to make it impossible.

---

## 10. Google sign-in for invited patients

Standard OIDC, with one rule that matters more than the plumbing: **the invitation
binds the identity, never the login.**

A patient is invited by the pharmacy, the invitation carries a single-use token,
the patient signs in with Google, and that Google subject is bound to that patient
row in that tenant. A Google sign-in on its own creates nothing and can claim
nothing — otherwise anybody who learns a patient's email address becomes them.

Worth planning for: a patient of two pharmacies has one Google account and two
patient records, so the portal has to let them choose. And Google is not universal
here, so an email-link sign-in should exist alongside it: a patient without a
Google account is a patient, not an edge case.

---

## What I would do first, and in what order

1. **Decide the tenancy model.** Everything else assumes it, and it is the hardest
   thing to change later.
2. **Per-action attribution and the idle lock.** Independent of tenancy, valuable
   to every pharmacy today, and the current gap is real.
3. **Tenant provisioning script**, which gives onboarding and demos at once.
4. **Platform database and admin.**
5. **Billing**, once the Paynow vendor account exists.
6. **Driver app** and the identity directory.
7. **Patient sign-in.**
