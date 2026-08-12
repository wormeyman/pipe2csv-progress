"""Locate the three files an extract ships with and derive its date."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_DATE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")


class MissingExtract(Exception):
    """No VRDB extract found in the folder."""


class AmbiguousExtract(Exception):
    """More than one file in the folder matches a pattern."""


@dataclass(frozen=True)
class ExtractFiles:
    vrdb: Path
    voting_history: Path | None
    districts: Path | None
    extract_date: str


def extract_date_from(path: Path) -> str:
    """YYYYMMDD from the filename, falling back to the file's mtime.

    Every match is validated as a real calendar date before it is accepted.
    Without that check the optional separator lets the pattern match straight
    across a year range: "2025-2026_Voting_History_20260601.txt" yields
    "20252026", meaning month 20 and day 26, instead of the real date later in
    the name.
    """
    for match in _DATE.finditer(path.name):
        stamp = "".join(match.groups())
        try:
            date.fromisoformat(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}")
        except ValueError:
            continue
        return stamp
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")


def _only(folder: Path, pattern: str) -> Path | None:
    """The single file matching `pattern`, or None.

    Refuses to choose when a folder holds more than one match. Picking the
    lexicographically first would silently load 20260401 over 20260803, and
    the run would produce correctly named output containing the wrong month.
    """
    matches = sorted(folder.glob(pattern))
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise AmbiguousExtract(
            f"{len(matches)} files in {folder} match {pattern}: {names}. "
            "Keep one extract per folder so the month loaded is never a guess."
        )
    return matches[0] if matches else None


def discover(folder) -> ExtractFiles:
    folder = Path(folder)
    # Prefer the .txt: it is the original CP1252 source. A sibling .csv is a
    # previously converted derivative.
    vrdb = _only(folder, "*VRDB_Extract.txt") or _only(folder, "*VRDB_Extract.csv")
    if vrdb is None:
        raise MissingExtract(f"no *VRDB_Extract.txt or .csv found in {folder}")
    return ExtractFiles(
        vrdb=vrdb,
        voting_history=_only(folder, "*Voting_History*.txt"),
        districts=_only(folder, "*Districts-Precincts.xlsx"),
        extract_date=extract_date_from(vrdb),
    )
