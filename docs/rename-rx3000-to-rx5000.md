# RX3000 → RX5000: what was renamed, and what deliberately was not

A product rename is a find-and-replace only for the strings nobody's data depends
on. Several of the occurrences of `rx3000` in this repository were **names of
things that already exist on somebody's disk**, and renaming those in place does
not migrate anything — it points the code at a new, empty thing and leaves the
old one unreachable. Each of those is listed here with the decision.

## Renamed outright (text nobody stores)

Wordmark on the shell and the login card, the browser and desktop window titles,
the FastAPI title, the portals' brand, the `[RX5000]` console prefix, CSV export
filenames, log channel names, the parity API field, prose in the source and docs,
`frontend/package.json`, and the Tauri `productName`.

## Renamed, with the old name still accepted

| Thing | Old | New | Why both |
|---|---|---|---|
| Session token | `rx3000_token` | `rx5000_token` | Renaming alone logs out every pharmacist mid-shift on first load. `frontend/src/storage.ts` reads the old key, adopts the value under the new one and deletes the old. |
| Sidebar / density prefs | `rx3000_rail`, `rx3000_density` | `rx5000_*` | Same mechanism; smaller stakes. |
| Env vars | `RX3000_*` | `RX5000_*` | Existing `.env` files, systemd units and Render dashboards carry the old spelling. `config.env()` reads new, falls back to old. Accepting only the new name would have silently reverted `RX3000_ENV=production` to `development`. |
| Desktop shell global | `__RX3000_SERVER__` | `__RX5000_SERVER__` | Shell and bundle ship together, but a desktop build from before the rename still injects the old global; reading only the new one drops that till to a localhost default it was configured away from. |
| `RX3000_SERVER` env in the shell | — | `RX5000_SERVER` | Same reason, Rust side. |
| Backup filenames | `rx3000-*.db`, `rx3000_*.db` | `rx5000-*.db` | `BACKUP_GLOBS` matches all four spellings, so no existing backup disappears from the restore screen. |

## Deliberately not renamed

- **IndexedDB database `rx3000-offline`.** It holds sales a till took while the
  line was down and has not posted yet. Opening a differently-named database
  creates an empty one; the queued sales stay on disk, unreachable. A pharmacy
  would discover this as missing takings. The name is visible only in devtools.
- **Tauri bundle identifier `zw.co.bitstudio.rx3000`.** On Windows this is the
  app's upgrade identity. Changing it makes the next installer a *different
  application*: it installs alongside the old one instead of replacing it, and
  the pharmacy ends up running two. Invisible to users.
- **An existing `backend/rx3000.db`.** New installations get `rx5000.db`;
  `_default_database_url()` adopts an `rx3000.db` that is already there rather
  than starting the pharmacy on an empty database beside their real one.

## Found while doing this

Two defects that the rename exposed rather than caused:

1. **Backups were written under two names and each listing saw only its own.**
   `POST /api/system/backup` wrote `rx3000-<stamp>.db`; `POST /api/admin/backup`
   wrote `rx3000_<stamp>.db`; the admin restore screen globbed only the
   underscore form. A pharmacist taking a backup from one screen could not find
   it on the other — which reads as "my backup did not save". Both now share one
   directory and one definition. The listing went from 7 files to the 16 that
   were actually there.
2. **`BACKUP_DIR` was resolved relative to the working directory**, so a service
   started from anywhere but `backend/` wrote backups where nothing looked for
   them. Now anchored to the backend directory, with the env override intact.
3. **Receipts printed "RX3000 Pharmacy" as the pharmacy's trading name**,
   hardcoded at three call sites. On software sold to many pharmacies, every
   printed receipt named the vendor instead of the shop. They now read
   `pharmacy_name` from `/api/jurisdiction`, which the backend has always
   returned. `printReceipt` no longer has a default for that parameter, so
   TypeScript names any call site that forgets it — it found a third one.
