"""Re-seeing an unchanged ad must be cheap on disk.

Every weekly crawl re-sees most of the corpus. In Postgres an UPDATE that
changes an indexed column writes a new entry into every index of the table
(~18 on `hub_job_postings`); one that changes only unindexed columns can be a
HOT update, which touches no index. `observation_id` is indexed, so moving it
on every touch turned each re-seen ad into ~19 writes and drained the Supabase
Disk IO budget (2026-11-12). An unchanged ad now only bumps `last_seen_at`;
`observation_id` keeps pointing at the fetch that produced its current content.
"""

from __future__ import annotations

import dataclasses
import re

from sqlalchemy import event, select

from app.core.database import SessionLocal, engine
from app.domain.hub.models import HubJobPosting
from tests.test_hub_ingest import StubAdapter, _fetch_result, _ingest


async def _observation_ids() -> dict[str, object]:
    async with SessionLocal() as session:
        rows = await session.execute(select(HubJobPosting.external_id, HubJobPosting.observation_id))
    return dict(rows.all())


async def test_an_unchanged_ad_keeps_the_observation_that_produced_it() -> None:
    first = await _ingest(StubAdapter())
    second = await _ingest(StubAdapter())
    assert second.observation_id != first.observation_id

    ids = await _observation_ids()
    assert ids and set(ids.values()) == {first.observation_id}


async def test_a_touch_writes_only_last_seen_at() -> None:
    await _ingest(StubAdapter())
    updates: list[str] = []

    def record(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith("UPDATE HUB_JOB_POSTINGS"):
            updates.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        await _ingest(StubAdapter())
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)

    assert updates, "a re-seen ad must still be stamped as seen"
    for statement in updates:
        columns = set(re.findall(r"(\w+)=", statement.split(" WHERE ")[0]))
        assert columns <= {"last_seen_at", "updated_at"}, statement  # updated_at: ORM onupdate, unindexed


async def test_a_changed_ad_moves_to_the_new_observation() -> None:
    first = await _ingest(StubAdapter())
    result = _fetch_result()
    changed = result.postings[0]
    result.postings[0] = dataclasses.replace(changed, title=changed.title + " (m/w/d) neu")
    second = await _ingest(StubAdapter(result))

    ids = await _observation_ids()
    assert ids[changed.external_id] == second.observation_id
    assert {v for k, v in ids.items() if k != changed.external_id} == {first.observation_id}
