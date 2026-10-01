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
to the log at startup, and shown on the This Till screen. Pointing a till at
the wrong server is the failure that wastes a support call, so it is visible
without hunting for it.

Not in the window title, which is where this file used to say it was. A
pharmacy reading "RX5000 Pharmacy Suite" followed by our hosting provider and
an endpoint across the top of their own software is being shown something that
is not theirs, and This Till answers the same question over a telephone, which
a title bar does not.

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

### Two things the installer needs, and which of them we carry

**The C runtime: ours, and inside the executable.** `.cargo/config.toml` links
it statically. Before that the till asked the machine for `VCRUNTIME140_1.dll`
and stopped with "the code execution cannot proceed" on any machine that had
never had a compiler on it — which is every machine we sell to.
`qa/a-till-starts-on-a-clean-machine.py` reads the built binary's imports and
fails if that comes back.

**The web view: Microsoft's, and usually already there.** The application is
drawn in WebView2. Windows 11 always has it and most Windows 10 machines do, so
the ordinary installer carries a few kilobytes that fetch it only if it is
missing. That keeps the download at 5 MB, which matters when somebody is
pulling it over a Zimbabwean line.

It does mean an install on a machine that has neither the runtime nor a
connection cannot finish. For those:

```
python desktop/publish.py 1.6.40 --offline
```

That embeds Microsoft's full runtime, produces
`RX5000_<version>_x64-setup-offline.exe` at 210 MB, measured, and publishes
nothing: the website goes on serving the small installer, and this one travels
on a memory stick to the counter that needs it. The build machine needs a
connection once, to embed the runtime.

The setting lives in `tauri.conf.json`, which is committed, so the script puts
the file back afterwards. A build that left it changed would make the next
ordinary one silently 210 MB and serve that to everybody, so it is restored byte
for byte and it is restored when the build fails too. Both are checked.

## Not in this shell yet

**Offline operation.** The shell runs against a server that must be reachable;
it does not yet hold its own store or reconcile after a disconnection. That is
the substantial remaining piece, and it is a data-integrity problem rather than
a packaging one: two tills that both sold the last box need a rule for who wins,
and inventing one quietly is worse than not having it.
