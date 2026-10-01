# -*- coding: utf-8 -*-
"""The built till asks the machine for nothing a clean Windows does not have.

WHAT WAS REPORTED

A pharmacy installing on a fresh machine got this before the window opened:

    rx5000.exe - System Error
    The code execution cannot proceed because VCRUNTIME140_1.dll was not
    found. Reinstalling the program may fix this problem.

WHAT IT WAS

Rust's MSVC toolchain links the Visual C++ runtime dynamically, so the binary
asked for VCRUNTIME140.dll and VCRUNTIME140_1.dll at start-up. Those ship with
the Microsoft Visual C++ Redistributable: present on every machine that has
ever had a compiler on it, absent on a clean Windows install.

Which is the worst shape a fault can have. It ran on every machine it was built
or tested on, and failed on every machine it was sold to.

WHAT THIS CHECKS

The import table of the binary that was actually built, against a list of what
a clean Windows 10 or 11 provides. Not the cargo flag that currently fixes it:
a flag can be right while the link is wrong — a dependency that brings its own
C library can drag the dynamic runtime back in, and the failure looks identical
to the user.

It reads the PE header itself rather than shelling out to dumpbin, which lives
inside a Visual Studio install and is therefore available on exactly the
machines where this fault cannot be reproduced.

WHAT IT CANNOT CHECK

WebView2. The till is a web view, and Tauri's installer fetches that runtime
separately; it is not an import of this binary, so nothing here would see it
missing. Windows 11 carries it, Windows 10 usually does, and the installer
downloads it where it does not — which needs the line to be up at install time.
That is a real exposure on a counter in Zimbabwe and it is a different fix.
"""
from __future__ import annotations

import io
import pathlib
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXE = ROOT / "desktop" / "src-tauri" / "target" / "release" / "rx5000.exe"

#: Asked for by name and not on a clean install. Each of these is part of the
#: Visual C++ Redistributable, which is a separate download from Microsoft.
NOT_ON_A_CLEAN_MACHINE = ("vcruntime", "msvcp", "msvcr", "concrt")


def imported_dlls(path: pathlib.Path) -> list[str]:
    """Every DLL named in a PE binary's import directory."""
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError(f"{path.name} is not a PE binary")
    sections = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    # Data directory 1 is the import table. Its offset differs between PE32 and
    # PE32+, which is the whole of the 32/64 bit difference that matters here.
    directories = opt + (112 if magic == 0x20B else 96)
    import_rva = struct.unpack_from("<I", data, directories + 8)[0]
    if not import_rva:
        return []

    table = []
    after = opt + opt_size
    for i in range(sections):
        at = after + i * 40
        va, raw_size, raw = struct.unpack_from("<III", data, at + 12)
        table.append((va, raw_size, raw))

    def file_offset(rva: int) -> int | None:
        for va, raw_size, raw in table:
            if va <= rva < va + max(raw_size, 1):
                return raw + (rva - va)
        return None

    out, i = [], 0
    base = file_offset(import_rva)
    while base is not None:
        entry = base + i * 20
        name_rva = struct.unpack_from("<I", data, entry + 12)[0]
        if name_rva == 0:
            break
        at = file_offset(name_rva)
        if at is None:
            break
        out.append(data[at:data.index(b"\0", at)].decode("ascii", "replace"))
        i += 1
    return out


def report() -> int:
    if not EXE.exists():
        print(f"No built till at {EXE}.\n"
              f"  Build one first: python desktop/publish.py <version>, or\n"
              f"  npx tauri build in desktop/src-tauri.")
        return 2
    dlls = imported_dlls(EXE)
    if not dlls:
        print(f"FAIL  {EXE.name} imports nothing, which cannot be right. The "
              f"import table could not be read.")
        return 1
    bad = sorted({d for d in dlls
                  if d.lower().startswith(NOT_ON_A_CLEAN_MACHINE)})
    if not bad:
        print(f"ok  {EXE.name} imports {len(dlls)} libraries, every one of them "
              f"part of Windows. It starts on a machine that has never had a "
              f"compiler on it.")
        return 0
    print(f"\nFAIL  {EXE.name} needs {len(bad)} library that a clean Windows "
          f"does not have\n")
    for d in bad:
        print(f"  {d}")
    print("\n  These ship with the Microsoft Visual C++ Redistributable. A")
    print("  pharmacy installing on a fresh machine is told the code execution")
    print("  cannot proceed, before the window opens, and reinstalling does not")
    print("  help because the file was never ours to install.")
    print("\n  desktop/src-tauri/.cargo/config.toml links the runtime in. If it")
    print("  is still there, something in the dependency tree is linking the")
    print("  dynamic one and has to be built static too.")
    return 1


if __name__ == "__main__":
    sys.exit(report())
