"""Reading whatever a customer exported from their old system.

Onboarding fails on the boring things. A German ATS exports CSV with
semicolons, cp1252 and a BOM; Excel writes .xlsx with merged header cells and
a sheet named "Tabelle1"; somebody opens the CSV in Excel and saves it again
with different quoting. None of that is interesting, all of it stops an
import, and a customer who hits it concludes the product does not work.

So: sniff rather than require. The only thing this module refuses is a file
it genuinely cannot read, and it says which of the three things was wrong.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

#: Encodings in the order German exports actually use them. utf-8-sig first
#: because it also matches plain utf-8 and strips the BOM Excel loves.
_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
#: Candidates for the delimiter. Semicolon first: on a German Windows locale
#: Excel writes `;` by default, and that is most of what arrives.
_DELIMITERS = ";,\t|"
#: A guard, not a judgement — a file this wide is a pivot table, not a list.
MAX_COLUMNS = 200


class UnreadableFile(ValueError):
    """The file cannot be parsed, with the reason in words."""


@dataclass
class Sheet:
    """A file reduced to what an import needs: headers and rows of strings."""

    columns: list[str]
    rows: list[dict[str, str]]
    #: How it was read, shown to the user so a mojibake column is explicable.
    note: str = ""
    problems: list[str] = field(default_factory=list)


def _decode(content: bytes) -> tuple[str, str]:
    """Bytes → text, trying the encodings German exports actually use."""
    for encoding in _ENCODINGS:
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    # latin-1 cannot fail, so reaching here means the file is not text at all.
    raise UnreadableFile(
        "Die Datei ist keine lesbare Textdatei — als CSV (UTF-8) oder .xlsx "
        "exportieren."
    )


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
    except csv.Error:
        # The sniffer gives up on a single-column file or an odd first line;
        # counting is right often enough and never raises.
        counts = {d: sample.count(d) for d in _DELIMITERS}
        best = max(counts, key=lambda d: counts[d])
        return best if counts[best] else ","


def read_csv(content: bytes) -> Sheet:
    text, encoding = _decode(content)
    if not text.strip():
        raise UnreadableFile("Die Datei ist leer.")
    delimiter = _sniff_delimiter(text[:4096])
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        raw_rows = list(reader)
    except csv.Error as exc:
        raise UnreadableFile(f"CSV konnte nicht gelesen werden: {exc}") from exc
    return _to_sheet(
        raw_rows,
        note=f"CSV · Trennzeichen „{delimiter}“ · {encoding}",
    )


def read_xlsx(content: bytes) -> Sheet:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise UnreadableFile("Excel-Unterstützung fehlt auf dem Server.") from exc

    try:
        # read_only keeps a 50k-row export from being materialised twice;
        # data_only takes the cached value of a formula rather than "=A1&B1".
        workbook = load_workbook(
            io.BytesIO(content), read_only=True, data_only=True
        )
    except Exception as exc:
        raise UnreadableFile(
            "Die Excel-Datei konnte nicht gelesen werden — .xls bitte vorher "
            "als .xlsx oder CSV speichern."
        ) from exc

    sheet = workbook[workbook.sheetnames[0]]
    raw_rows = [
        ["" if cell is None else str(cell).strip() for cell in row]
        for row in sheet.iter_rows(values_only=True)
    ]
    workbook.close()
    return _to_sheet(
        raw_rows,
        note=f"Excel · Blatt „{sheet.title}“ von {len(workbook.sheetnames)}",
    )


def _to_sheet(raw_rows: list[list], *, note: str) -> Sheet:
    """Rows of cells → a header plus dict rows, with the usual mess handled."""
    rows = [[str(c).strip() if c is not None else "" for c in row] for row in raw_rows]
    problems: list[str] = []

    # Find the header row.
    #
    # Exports routinely start with a title ("Export Kandidaten", "Stand
    # 03.10.2026") above the table. Counting non-empty cells is not enough —
    # a title with two cells beats a "≥2 cells" rule and turns every column
    # into "Spalte 3", which is how this was measured and found wrong.
    #
    # The header is the first row that is as WIDE as the data. Take the most
    # common filled-cell count across the file as the table's width and skip
    # anything narrower; a title has one or two cells, a header has all of
    # them. `modal - 1` tolerates a header whose last column is unnamed.
    from collections import Counter

    widths = Counter(sum(1 for cell in row if cell) for row in rows if any(row))
    modal = max(widths, key=lambda w: (widths[w], w)) if widths else 0
    threshold = max(1, modal - 1)

    skipped = 0
    while rows and sum(1 for cell in rows[0] if cell) < threshold:
        rows.pop(0)
        skipped += 1
    if skipped:
        problems.append(
            f"{skipped} Zeile(n) über der Tabelle übersprungen — die erste "
            "Zeile mit der vollen Spaltenzahl gilt als Kopfzeile."
        )

    if not rows:
        raise UnreadableFile("Die Datei enthält keine Zeilen.")

    header, *body = rows
    columns: list[str] = []
    seen: dict[str, int] = {}
    for index, name in enumerate(header):
        label = name.strip() or f"Spalte {index + 1}"
        if label in seen:
            # Two columns called "Telefon" is common and must not silently
            # overwrite one another.
            seen[label] += 1
            label = f"{label} ({seen[label]})"
        else:
            seen[label] = 1
        columns.append(label)

    if len(columns) > MAX_COLUMNS:
        raise UnreadableFile(
            f"{len(columns)} Spalten — das sieht nicht nach einer Liste aus."
        )

    parsed: list[dict[str, str]] = []
    for row in body:
        if not any(cell for cell in row):
            continue  # blank separator lines
        if len(row) > len(columns):
            problems.append(
                "Mindestens eine Zeile hat mehr Werte als Spalten — "
                "überzählige Werte werden ignoriert."
            )
        parsed.append(
            {
                column: (row[i] if i < len(row) else "")
                for i, column in enumerate(columns)
            }
        )

    return Sheet(
        columns=columns,
        rows=parsed,
        note=note,
        problems=list(dict.fromkeys(problems)),
    )


def read(filename: str, content: bytes) -> Sheet:
    """Read by extension, falling back to CSV — the content decides."""
    lowered = filename.lower()
    if lowered.endswith((".xlsx", ".xlsm")):
        return read_xlsx(content)
    if lowered.endswith(".xls"):
        raise UnreadableFile(
            "Das alte .xls-Format wird nicht gelesen — bitte als .xlsx oder "
            "CSV speichern."
        )
    return read_csv(content)
