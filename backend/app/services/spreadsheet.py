"""Turn whatever the wholesaler sent into the rows the importer reads.

Every import in this product takes CSV text, and every supplier and every
legacy system sends a spreadsheet. The pharmacy's own answer was to open the
file in Excel, save as CSV, find the dialogue about keeping the format, and
then upload it. That works, and it is a step where dates silently become
American, leading zeros are eaten off a stock code, and a pharmacist decides
the software is difficult.

Reports already export real xlsx, so openpyxl is here. This is the same
courtesy in the other direction.

WHAT IT DOES NOT DO

It does not guess which sheet. A workbook with four sheets is a question, not
a file, and picking the first one silently is how somebody imports last year's
price list. The sheet names come back with the rows so the screen can ask.

It does not reformat anything. A cell is rendered as the text a person would
see in the spreadsheet, and nothing is parsed into a date or a number here:
the importer already knows how to read the columns it wants, and a second
opinion about types on the way in is how a stock code becomes 1.2E+11.
"""
from __future__ import annotations

import csv
import io

#: Anything larger is a database export rather than a price list, and reading
#: it into memory to convert it would take the server down for everybody.
MAX_BYTES = 12 * 1024 * 1024

#: Excel's own limit is a million rows. A pharmacy price list is thousands.
MAX_ROWS = 200_000


class SpreadsheetError(ValueError):
    """Raised with a sentence somebody at a counter can act on."""


def _cell(value) -> str:
    """One cell as the text a person would see in the spreadsheet.

    Deliberately not clever. The one place it has to be is a whole number
    arriving as a float: openpyxl reads a stock code typed as a number as
    1234.0, and "1234.0" matches nothing in a catalogue.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value).strip()


def sheets(data: bytes) -> list[str]:
    """What is in the workbook, so somebody can be asked which one."""
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        return list(book.sheetnames)
    finally:
        book.close()


def to_csv(data: bytes, *, sheet: str = "") -> tuple[str, str, int]:
    """A workbook as CSV text. Returns (csv_text, sheet_used, rows).

    `data_only` so a cell holding a formula gives its last computed value
    rather than "=B2*1.15", which no importer can read and which is what a
    supplier's markup column usually is.
    """
    if len(data) > MAX_BYTES:
        raise SpreadsheetError(
            f"That file is {len(data) // (1024 * 1024)}MB. Anything over "
            f"{MAX_BYTES // (1024 * 1024)}MB is a database export rather than "
            "a price list, and it has to be split.")

    from openpyxl import load_workbook
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:                                   # noqa: BLE001
        raise SpreadsheetError(
            "That file could not be opened as a spreadsheet. If it came from "
            "an older system, open it and save it as .xlsx or .csv first."
        ) from exc

    try:
        if sheet and sheet not in book.sheetnames:
            raise SpreadsheetError(
                f"There is no sheet called {sheet!r} in that workbook. It has: "
                + ", ".join(book.sheetnames) + ".")
        ws = book[sheet] if sheet else book[book.sheetnames[0]]

        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        written = 0
        # THE TITLE BLOCK ON TOP OF A REAL EXPORT.
        #
        # A pharmacy's own stock export does not begin with its column names.
        # It begins with the shop's name, its address, its telephone number and
        # the title of the report, each alone on a row, and the header is the
        # sixth line down. Handing that to the importer gets "nothing in this
        # file identifies a product", which is true of row one and wrong about
        # the file.
        #
        # A title line is one cell wide; a header is not. So leading rows with
        # fewer than two filled cells are dropped, and dropping stops at the
        # first row that has two, which is the header. Nothing after that is
        # touched: a one cell row in the middle of the data is somebody's note,
        # and the importer can refuse it on its own terms.
        started = False
        for row in ws.iter_rows(values_only=True):
            cells = [_cell(v) for v in row]
            # A wholly empty row is a spacer somebody left in, not a record.
            # Trailing ones are what make a 900 row file look like 4,000.
            if not any(cells):
                continue
            if not started:
                if sum(1 for c in cells if c) < 2:
                    continue
                started = True
            writer.writerow(cells)
            written += 1
            if written > MAX_ROWS:
                raise SpreadsheetError(
                    f"That sheet has more than {MAX_ROWS:,} rows, which is more "
                    "than a price list and more than this can take at once.")

        if not written:
            raise SpreadsheetError(
                f"The sheet {ws.title!r} is empty. The workbook also has: "
                + ", ".join(n for n in book.sheetnames if n != ws.title) + ".")

        return out.getvalue(), ws.title, written
    finally:
        book.close()


def read_any(data: bytes, filename: str, *, sheet: str = "") -> tuple[str, str, int]:
    """CSV text from whatever was uploaded, spreadsheet or not."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        return to_csv(data, sheet=sheet)
    if name.endswith(".xls"):
        raise SpreadsheetError(
            "That is the old Excel format, which this cannot read. Open it and "
            "save it as .xlsx or .csv, and it will load.")
    # Plain text. Utf-8 first, then the encoding Excel writes on a Windows
    # machine in this region, which is where most of these files come from.
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding), "", data.count(b"\n") + 1
        except UnicodeDecodeError:
            continue
    raise SpreadsheetError("That file is not text this can read.")
