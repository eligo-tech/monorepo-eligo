"""One search request matches the ad text once per term, not once per query.

Measured on production 2026-11-03 (read-only EXPLAIN ANALYZE, q="SAP"): the
ad-text match took 1.29–1.40 s and ran TWICE per request — once for the result
page, once for the total — about 2.6 s of a 3.8–4.3 s search. The page and the
count read the same corpus in the same request, so the second run is pure cost.
"""

from __future__ import annotations

from sqlalchemy import event

from app.core.database import SessionLocal, engine
from app.domain.hub import service


def _count_ad_text_queries(statements: list[str]) -> int:
    return sum(
        1 for s in statements if "hub_posting_payload" in s and "lower(hub_posting_payload.description) LIKE" in s
    )


async def test_the_page_and_the_count_share_one_ad_text_match() -> None:
    seen: list[str] = []

    def record(conn, cursor, statement, params, context, many):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        async with SessionLocal() as s:
            await service.search_employers(s, q="sap entwickler", limit=40)
            await service.count_employers(s, q="sap entwickler")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)

    assert _count_ad_text_queries(seen) == 2  # one per term, not one per term per query


async def test_a_new_request_matches_again() -> None:
    # The memo lives on the session — one request — so tonight's ads are seen
    # by tomorrow's searches.
    seen: list[str] = []

    def record(conn, cursor, statement, params, context, many):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        for _ in range(2):
            async with SessionLocal() as s:
                await service.count_employers(s, q="sap")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)

    assert _count_ad_text_queries(seen) == 2
