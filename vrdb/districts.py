"""Streaming reader for the Districts-Precincts workbook.

Trust boundary: the input is a workbook the operator downloaded from the WA
Secretary of State and already opens in Excel, parsed locally. stdlib
ElementTree is fine for that. If this ever ingests workbooks from untrusted
senders, swap the import for defusedxml.ElementTree, which is a drop-in and
blocks entity-expansion attacks that stdlib ElementTree does not.

Stdlib only. The real workbook declares dimension A1:H237379 but holds 231,537
data rows: 3,592 row numbers have no element at all, and 2,249 of the elements
that do exist are entirely empty. Trusting `dimension`, or emitting one row per
<row> element, invents phantom all-null district rows. So: never read the
declared dimension, and skip rows where every cell is empty.
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from vrdb import reader, schema

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL = re.compile(r"[A-Z]+")


def _column_index(ref: str) -> int:
    """'A1' -> 0, 'H12' -> 7, 'AA3' -> 26."""
    match = _COL.match(ref)
    if match is None:
        raise ValueError(f"malformed cell reference: {ref!r}")
    letters = match.group(0)
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    return ["".join(t.text or "" for t in si.iter(_NS + "t")) for si in root]


def iter_rows(path, width: int = 8):
    """Yield each non-empty sheet row as a list of `width` strings.

    `element` and `cell` are annotated because typeshed types ET.iterparse as
    Iterator[tuple[str, Any]]. Without the annotation the whole body below is
    unchecked Any, which is how a `str | None` reached _column_index(ref: str).
    """
    path = Path(path)
    element: ET.Element
    with zipfile.ZipFile(path) as archive:
        strings = _shared_strings(archive)
        with archive.open("xl/worksheets/sheet1.xml") as sheet:
            for _, element in ET.iterparse(sheet, events=("end",)):
                if element.tag != _NS + "row":
                    continue
                cells = [""] * width
                index = -1
                cell: ET.Element
                for cell in element.iter(_NS + "c"):
                    ref = cell.get("r")
                    # OOXML permits omitting r=, in which case the cell sits in
                    # the column after the previous one. A writer that does so
                    # used to raise TypeError from inside _column_index rather
                    # than the diagnosable ValueError.
                    index = _column_index(ref) if ref is not None else index + 1
                    if index >= width:
                        continue
                    kind = cell.get("t")
                    if kind == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter(_NS + "t"))
                    else:
                        node = cell.find(_NS + "v")
                        if node is None or node.text is None:
                            value = ""
                        elif kind == "s":
                            value = strings[int(node.text)]
                        else:
                            value = node.text
                    cells[index] = value
                element.clear()
                if any(cells):
                    yield cells


def iter_batches(
    path,
    table: schema.Table = schema.DISTRICTS_PRECINCTS,
    *,
    batch_size: int = 50_000,
    stats: reader.ReadStats | None = None,
    progress=None,
):
    """Yield lists of coerced rows, matching reader.iter_batches."""
    stats = stats if stats is not None else reader.ReadStats()
    kinds = [c.kind for c in table.columns]
    names = list(table.column_names)
    width = len(kinds)

    rows = iter_rows(path, width=width)
    first = next(rows, None)
    if first is None:
        return
    # Validate row 1 instead of discarding it, mirroring reader.iter_batches.
    # Discarding it meant a workbook whose columns had been reordered - swap
    # DistrictName and PrecinctName, say - loaded silently at full join
    # coverage, because the join only exercises (CountyCode, PrecinctPart).
    header = [c.strip() for c in first]
    if header != names:
        raise reader.HeaderMismatch(
            f"{Path(path).name}: expected columns {names}, found {header}"
        )

    batch = []
    for cells in rows:
        batch.append([reader.coerce(v, k) for v, k in zip(cells, kinds)])
        stats.rows += 1
        if len(batch) >= batch_size:
            yield batch
            batch = []
        if progress is not None:
            progress.update(stats.rows, 0)
    if batch:
        yield batch
