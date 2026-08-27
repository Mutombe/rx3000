# -*- mode: python ; coding: utf-8 -*-
"""Freeze the backend into one executable for the desktop app to carry.

Two things need saying, because both are the sort of failure that only shows up
on a machine that is not this one.

**Everything is collected, not inferred.** PyInstaller finds imports by reading
the source, and this application does not import several of its own parts by
name: routers arrive through a loop, uvicorn loads its protocol implementations
by string, and SQLAlchemy picks a dialect at runtime from the URL. Left to the
analyser those simply are not in the bundle, and the binary starts and then dies
on the first request with a ModuleNotFoundError.

**It is one file, deliberately.** A directory build starts faster, but it means
an installer that lays down four hundred files, and every one of them is
something a virus scanner, a sync client or a tidy-minded owner can remove. One
executable is the thing that either exists or does not.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hidden = []
for package in ("uvicorn", "fastapi", "starlette", "pydantic",
                "sqlalchemy", "anyio", "email_validator", "passlib", "jose"):
    hidden += collect_submodules(package)

# The routers are included through a loop over a tuple, and the services are
# reached through `from .services import x` inside functions. Neither pattern is
# visible to static analysis.
hidden += collect_submodules("app")

datas = collect_data_files("fastapi") + collect_data_files("passlib")

a = Analysis(
    ["server_main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Not needed by a server and heavy enough to be worth refusing: a pharmacy
    # downloading this over a Zimbabwean line pays for every megabyte.
    # `py` and `_pytest` are excluded by name as well as `pytest`: the
    # analyser followed a transitive import into `py._path` and the child
    # process died outright rather than reporting a missing module.
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "IPython",
              "pytest", "_pytest", "py", "py._path", "pluggy",
              "setuptools", "pip", "PyInstaller"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="rx5000-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No console window on Windows: the desktop app starts this, and a black
    # box appearing behind the till screen looks like something went wrong.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
