"""A backup on the same disk as the database is not a backup.

It survives somebody deleting a row. It does not survive the disk, the theft of
the till, or the fire, and `backup.py` says out loud that one disk failure ends
the business. Until now the only answer to that was a folder on that same disk.

On the hosted deployment it was worse than unhelpful. Render gives a container
an ephemeral filesystem, so the nightly job wrote a verified file onto a disk
the next deploy threw away, and the screen said the pharmacy was protected.

So this checks the three claims the feature actually makes:

  - with nothing configured, nothing changes and nothing pretends otherwise.
    Most installs of this product are one machine in a back office with no
    bucket and no interest in one.
  - a half-configured bucket is treated as no bucket, and says which part is
    missing. Half configured is the state where the upload fails every night
    at two in the morning and nobody hears about it until a backup is needed.
  - being configured and being reachable are different claims, and the screen
    that tells a pharmacy it is protected must be making the second one.

Reaching a real bucket is not checked here. That needs credentials and a
network, and a test that is skipped when either is missing is a test nobody
notices has stopped running.

    python tests/test_a_backup_leaves_the_machine.py
"""
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ok = True


def check(cond, label, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"{'ok  ' if cond else 'FAIL'}  {label}{'   ' + str(extra) if extra else ''}")


def objects_with(**env):
    """Reload the module under a given environment.

    Its configuration is read at import, which is right for a process that is
    configured once at boot and wrong for a test, so the module is rebuilt.
    """
    for key in ("SPACES_ENDPOINT", "SPACES_BUCKET", "SPACES_KEY",
                "SPACES_SECRET", "SPACES_REGION", "SPACES_PREFIX"):
        os.environ.pop("RX5000_" + key, None)
        os.environ.pop("RX3000_" + key, None)
    for key, value in env.items():
        os.environ["RX5000_" + key] = value
    import app.services.objects as objects
    return importlib.reload(objects)


# ---- nothing configured ----------------------------------------------------
o = objects_with()
check(not o.enabled(), "with no bucket configured, it is switched off")
check("only on this machine" in o.why_not(),
      "and says so in words a pharmacist can act on", o.why_not())
state = o.check()
check(state["configured"] is False and state["reachable"] is False,
      "neither configured nor reachable")
check(o.put_file(Path(__file__), "backups", "x.db").ok is False,
      "an upload is a no-op rather than an error")
check(o.listing("backups") == [], "and there is nothing to list")

# ---- half configured is not configured -------------------------------------
o = objects_with(SPACES_ENDPOINT="https://sfo3.digitaloceanspaces.com",
                 SPACES_BUCKET="rx5000")
check(not o.enabled(), "a bucket with no key is not a bucket")
missing = o.why_not()
check("SPACES_KEY" in missing and "SPACES_SECRET" in missing,
      "and it names exactly what is missing", missing)

# ---- fully configured ------------------------------------------------------
o = objects_with(SPACES_ENDPOINT="https://sfo3.digitaloceanspaces.com",
                 SPACES_BUCKET="rx5000", SPACES_REGION="sfo3",
                 SPACES_KEY="not-a-real-key", SPACES_SECRET="not-a-real-secret")
check(o.enabled(), "all five present is configured")
check(o.why_not() == "", "with nothing left to explain")

# Keys are built under one prefix, so a bucket shared with something else stays
# legible and a lifecycle rule can be aimed at us without catching their files.
check(o.key_for("backups", "rx5000-20260919.db")
      == "rx5000/backups/rx5000-20260919.db",
      "everything is written under one prefix", o.key_for("backups", "a.db"))
check(o.key_for("backups", "", "a.db") == "rx5000/backups/a.db",
      "and an empty part does not become a doubled separator")

# ---- the backup result carries the second promise ---------------------------
import app.services.backup as backup                               # noqa: E402
importlib.reload(backup)
check(hasattr(backup, "objects"), "the backup path knows about off-machine storage")
src = Path(backup.__file__).read_text(encoding="utf-8")
at_upload = src.index("objects.put_file")
at_verify = src.index("failed verification")
check(at_verify < at_upload,
      "and it uploads only AFTER verification, never a copy nobody checked")
check("off_machine" in src, "the result says whether the copy left the machine")

print()
print("a backup can leave the machine, and says when it has not." if ok else "FAILED")
sys.exit(0 if ok else 1)
