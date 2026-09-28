# RX3000 desktop

The till application. A Tauri shell around the same front end the browser runs,
because a counter is not a web page: it drives a receipt printer, a cash drawer
and a fiscal device, and it has to keep serving patients when the line is down.

Tauri rather than Electron. Three reasons, in the order they matter here:

* **Download size.** A Tauri installer is single-digit megabytes against
  Electron's hundred-plus. Pharmacies update over Zimbabwean connections, often
  metered, sometimes tethered.
* **Memory.** Tills are old machines. Four tabs of Chromium each holding its own
  runtime is how a 4 GB counter PC starts swapping at eleven in the morning.
* **The hardware is already handled.** The device agent owns the printer, the
  drawer and the fiscal device over HTTP, so the shell does not need Node in the
  main process. Electron's chief advantage did not apply.

## Which server a till talks to

Each pharmacy runs its own backend on the premises. A build with a hard-coded
address would be a build per customer, so the address is configuration:

1. `RX3000_SERVER` in the environment — an operator overriding for one run
2. `server.txt` beside the executable — what the installer or IT writes
3. `http://localhost:8177` — the single-machine pharmacy

The resolved address is injected into the page before any script runs, printed
to the log at startup, and shown in the window title. Pointing a till at the
wrong server is the failure that wastes a support call, so it is visible without
opening a settings screen.

## Building

Use the publish script. It sets the version in both places that carry one,
builds the front end, builds the installers, copies them into the site's
downloads folder and checks the page's links resolve:

```
python desktop/publish.py 1.5.1
```

By hand needs the Rust toolchain and the Tauri CLI:

```
cargo install tauri-cli --version "^2"
cd desktop/src-tauri
cargo tauri build
```

`beforeBuildCommand` in `tauri.conf.json` builds the front end, so this is safe
to run on its own now. It was not always: `frontendDist` points at
`frontend/dist` and the shell embeds whatever is sitting there, so before that
line existed a bare `tauri build` shipped the last build somebody happened to
make. `publish.py` still checks the bundle's age afterwards and refuses to
publish one older than half an hour, because the installers are the one
artefact nobody can tell is stale by looking at it.

## Not in this shell yet

**Offline operation.** The shell runs against a server that must be reachable;
it does not yet hold its own store or reconcile after a disconnection. That is
the substantial remaining piece, and it is a data-integrity problem rather than
a packaging one: two tills that both sold the last box need a rule for who wins,
and inventing one quietly is worse than not having it.
