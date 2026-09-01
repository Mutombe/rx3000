"""Report engine and catalogue.

`definitions` is imported for its side effect: importing it runs every
`register(...)` call, which is what puts anything in the catalogue. It is not an
unused import, whatever a linter says.

It is also imported *first*, and the module is called `definitions` rather than
`catalogue`, because `engine.catalogue()` is a function of that name, and a
submodule that collides with an already-bound attribute of its own package is
silently never executed. That produced an empty catalogue with no error at all,
which is exactly the kind of failure worth designing out rather than commenting.
"""
from . import definitions  # noqa: F401  (registers every report)
from .engine import (  # noqa: F401
    Column, Param, Report, REGISTRY, catalogue, run, to_csv, to_xlsx,
)
