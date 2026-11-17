"""`scripts/fill_every_table` must satisfy a one-of check (CI "upgrade from main").

`follow_ups` (0074) requires exactly one of `manager_id` / `candidate_id`
(`ck_follow_ups_one_person`). The script pointed every foreign key at its
parent's row, so it set both and every PR's upgrade job failed on the
check. Postgres reflects the constraint as
`((manager_id IS NULL) <> (candidate_id IS NULL))`.
"""

from sqlalchemy import CheckConstraint, Column, MetaData, Table, text

from scripts.fill_every_table import _left_null


def _table(sql: str) -> Table:
    return Table(
        "t", MetaData(),
        Column("a_id", nullable=True), Column("b_id", nullable=True),
        CheckConstraint(text(sql), name="ck_one"),
    )


def test_one_of_check_leaves_the_second_column_null() -> None:
    assert _left_null(_table("((a_id IS NULL) <> (b_id IS NULL))")) == {"b_id"}


def test_other_checks_leave_nothing_null() -> None:
    assert _left_null(_table("a_id IS NOT NULL")) == set()
