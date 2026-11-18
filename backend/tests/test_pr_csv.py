"""The PR batch parser is forgiving (D17): only a missing required column rejects a batch."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from engine.inputs import PRLine
from loaders.pr_csv import BatchFormatError, parse_pr_csv

HEADER = ("pr_no,pr_line,created_at,requester,department,plant,item_code,description,quantity,uom,"
          "estimated_unit_price,need_by_date,urgency")
ROW = "PR-1,1,2026-11-04 12:40,A. Rao,Stores,PUN1,ITM-1002,MS sheet 3mm 1250x2500,15,NOS,,2026-11-15,Normal"


def one(text):
    rows = parse_pr_csv(text)
    assert len(rows) == 1
    return rows[0][1]


def test_the_sample_format_parses():
    line = one(f"{HEADER}\n{ROW}\n")
    assert line["created_at"] == datetime(2026, 11, 4, 12, 40)
    assert (line["pr_line"], line["quantity"], line["estimated_unit_price"]) == ("1", Decimal("15"), None)
    assert PRLine(**line).need_by_date == date(2026, 11, 15)


@pytest.mark.parametrize("text", [
    f"﻿{HEADER}\n{ROW}\n",                                  # byte-order mark
    f"{HEADER}\r\n{ROW}\r\n",                                    # Windows line endings
    f"{HEADER}\n{ROW}\n\n,,,\n   \n",                            # blank trailing rows
    f"{HEADER.upper().replace(',', ' , ')}\n{ROW}\n",            # header in upper case with stray spaces
    f"{HEADER},extra_column\n{ROW},whatever\n",                  # extra column
    f"{HEADER}\n{ROW.replace(',', ' , ')}\n",                    # spaces around every cell
])
def test_tolerated_variations_give_the_same_line(text):
    assert one(text) == one(f"{HEADER}\n{ROW}\n")


def test_columns_in_any_order_and_optional_columns_absent():
    text = "need_by_date,quantity,description,plant,created_at,pr_line,pr_no\n2026-11-15,15,MS sheet,PUN1,2026-11-04 12:40,1,PR-1\n"
    line = one(text)
    assert (line["pr_no"], line["quantity"], line["item_code"], line["urgency"], line["uom"]) == ("PR-1", Decimal("15"), None, None, None)


@pytest.mark.parametrize("stamp, expected", [
    ("2026-11-04 12:40", datetime(2026, 11, 4, 12, 40)),
    ("2026-11-04 12:40:30", datetime(2026, 11, 4, 12, 40, 30)),
    ("2026-11-04T12:40", datetime(2026, 11, 4, 12, 40)),
    ("2026-11-04T12:40:30", datetime(2026, 11, 4, 12, 40, 30)),
    ("yesterday", None),          # unreadable: this line only becomes NOT_PROCESSED (line check V7)
    ("", None),
])
def test_timestamps_with_or_without_seconds_or_T(stamp, expected):
    assert one(f"{HEADER}\n{ROW.replace('2026-11-04 12:40', stamp)}\n")["created_at"] == expected


def test_unreadable_cells_become_none_and_the_rest_of_the_batch_survives():
    bad = ROW.replace(",15,", ",lots,").replace("2026-11-15", "next week").replace("2026-11-04 12:40", "soon")
    rows = parse_pr_csv(f"{HEADER}\n{bad}\n{ROW.replace('PR-1', 'PR-2')}\n")
    assert len(rows) == 2
    first = rows[0][1]
    assert (first["quantity"], first["need_by_date"], first["created_at"]) == (None, None, None)
    assert rows[0][0]["quantity"] == "lots"  # the raw text is kept
    assert rows[1][1]["quantity"] == Decimal("15")


def test_a_whole_batch_is_rejected_only_for_a_missing_column_an_empty_file_or_broken_quoting():
    """Bad cells fail only their own line (D17); these make the file itself unreadable (break-it pass)."""
    with pytest.raises(BatchFormatError, match="need_by_date"):
        parse_pr_csv(HEADER.replace(",need_by_date", "") + "\n2026-11-20\n")
    with pytest.raises(BatchFormatError, match="the file is empty"):
        parse_pr_csv("")
    with pytest.raises(BatchFormatError, match="a header but no lines"):
        parse_pr_csv(HEADER + "\n\n")
    with pytest.raises(BatchFormatError, match="line 2 is not valid CSV"):
        parse_pr_csv(HEADER + '\nPR-1,1,2026-11-05 10:00,A,B,PUN1,,"unclosed,1,NOS,,2026-11-20,Normal\n')
