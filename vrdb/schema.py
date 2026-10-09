"""Single source of truth for VRDB table shapes.

Stdlib only on purpose: this module must stay importable without pyarrow so
the readers and SQLite writer can be tested independently. The kind-to-Arrow
mapping lives in parquet_out.py.

Column names and order follow the actual extract headers, not
"VRDB Database Fields 2.pdf", which is wrong in three places (see the design
spec).
"""

from dataclasses import dataclass

KIND_TEXT = "text"
KIND_INT = "int"
KIND_DATE = "date"

_SQLITE_TYPES = {KIND_TEXT: "TEXT", KIND_INT: "INTEGER", KIND_DATE: "TEXT"}


def sqlite_type(kind: str) -> str:
    """SQLite declared type for a column kind.

    Dates are TEXT: SQLite has no date type, and ISO YYYY-MM-DD strings sort
    and compare correctly with <, BETWEEN and date().
    """
    try:
        return _SQLITE_TYPES[kind]
    except KeyError:
        raise ValueError(f"unknown column kind: {kind!r}") from None


@dataclass(frozen=True)
class Column:
    name: str
    kind: str
    primary_key: bool = False


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    indexes: tuple[Index, ...] = ()

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    @property
    def primary_key(self) -> Column | None:
        for c in self.columns:
            if c.primary_key:
                return c
        return None


def _t(name: str) -> Column:
    return Column(name, KIND_TEXT)


VOTERS = Table(
    name="voters",
    columns=(
        Column("StateVoterID", KIND_INT, primary_key=True),
        _t("FName"),
        _t("MName"),
        _t("LName"),
        _t("NameSuffix"),
        Column("Birthyear", KIND_INT),
        _t("Gender"),
        _t("RegStNum"),  # 23,093 rows like "123A"
        _t("RegStFrac"),
        _t("RegStName"),
        _t("RegStType"),
        _t("RegUnitType"),
        _t("RegStPreDirection"),
        _t("RegStPostDirection"),
        _t("RegStUnitNum"),
        _t("RegCity"),
        _t("RegState"),
        _t("RegZipCode"),  # ZIP+4 present
        _t("CountyCode"),
        _t("PrecinctCode"),  # leading zeros significant
        _t("PrecinctPart"),  # format varies by county, match literally
        Column("LegislativeDistrict", KIND_INT),
        Column("CongressionalDistrict", KIND_INT),
        _t("Mail1"),
        _t("Mail2"),
        _t("Mail3"),  # always empty in the 2026-08 extract
        _t("MailCity"),
        _t("MailZip"),
        _t("MailState"),
        _t("MailCountry"),
        Column("Registrationdate", KIND_DATE),
        Column("LastVoted", KIND_DATE),
        _t("StatusCode"),
    ),
    indexes=(
        Index("idx_voters_county", ("CountyCode",)),
        Index("idx_voters_status", ("StatusCode",)),
        Index("idx_voters_precinct", ("CountyCode", "PrecinctCode")),
        Index("idx_voters_precinctpart", ("CountyCode", "PrecinctPart")),
        Index("idx_voters_legislative", ("LegislativeDistrict",)),
        Index("idx_voters_congressional", ("CongressionalDistrict",)),
        Index("idx_voters_lastvoted", ("LastVoted",)),
        Index("idx_voters_name", ("LName", "FName")),
    ),
)

VOTING_HISTORY = Table(
    name="voting_history",
    columns=(
        Column("VoterHistoryID", KIND_INT, primary_key=True),
        _t("CountyCode"),
        _t("CountyCode_Voting"),
        Column("StateVoterID", KIND_INT),
        Column("ElectionDate", KIND_DATE),
    ),
    indexes=(
        Index("idx_vh_statevoterid", ("StateVoterID",)),
        Index("idx_vh_electiondate", ("ElectionDate",)),
    ),
)

DISTRICTS_PRECINCTS = Table(
    name="districts_precincts",
    columns=(
        _t("CountyCode"),
        _t("County"),
        _t("DistrictType"),
        _t("DistrictCode"),
        _t("DistrictName"),
        _t("PrecinctCode"),
        _t("PrecinctName"),
        _t("PrecinctPart"),
    ),
    indexes=(
        Index("idx_dp_precinctpart", ("CountyCode", "PrecinctPart")),
        Index("idx_dp_districtname", ("DistrictName",)),
    ),
)

ALL_TABLES = (VOTERS, VOTING_HISTORY, DISTRICTS_PRECINCTS)

COUNTY_CODES = {
    "AD": "Adams", "AS": "Asotin", "BE": "Benton", "CH": "Chelan",
    "CM": "Clallam", "CR": "Clark", "CU": "Columbia", "CZ": "Cowlitz",
    "DG": "Douglas", "FE": "Ferry", "FR": "Franklin", "GA": "Garfield",
    "GR": "Grant", "GY": "Grays Harbor", "IS": "Island", "JE": "Jefferson",
    "KI": "King", "KP": "Kitsap", "KS": "Kittitas", "KT": "Klickitat",
    "LE": "Lewis", "LI": "Lincoln", "MA": "Mason", "OK": "Okanogan",
    "PA": "Pacific", "PE": "Pend Oreille", "PI": "Pierce", "SJ": "San Juan",
    "SK": "Skagit", "SM": "Skamania", "SN": "Snohomish", "SP": "Spokane",
    "ST": "Stevens", "TH": "Thurston", "WK": "Wahkiakum", "WL": "Walla Walla",
    "WM": "Whatcom", "WT": "Whitman", "YA": "Yakima",
}

GENDER_CODES = {
    "M": "Male",
    "F": "Female",
    "U": "Unknown/Not Provided",
    "O": "Other",
}

STATUS_CODES = {
    "Active": "",
    "Inactive": "See RCW 29A.08.620 for reasons a voter would be assigned inactive status",
    "Pending - Primary Only Voter": (
        "17 on the day of the primary but 18 on or before the following November "
        "general election; may vote in primaries only"
    ),
}


# The lookup tables, so a query can read 'King' instead of 'KI'. Both the
# SQLite database and the DuckDB views file carry them: (name, columns, mapping).
REF_TABLES = (
    ("ref_county", ("code", "name"), COUNTY_CODES),
    ("ref_gender", ("code", "name"), GENDER_CODES),
    ("ref_status", ("code", "note"), STATUS_CODES),
)
