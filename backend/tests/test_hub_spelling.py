"""A search word the corpus has never seen, rewritten to one it has.

Measured on the live corpus before this existed:

    lower(city) like '%münchen%'    3,122 rows
    lower(city) like '%muenchen%'       0 rows
    lower(title) like '%embedded%'    188 rows
    lower(title) like '%embeded%'       0 rows

Both zeroes were the search failing, not the corpus being empty.

CI runs SQLite, which has no pg_trgm, so the trigram half of the fallback
cannot be exercised here — `_nearest_known_word` returns None off Postgres.
The umlaut half is dialect-independent and is what these tests pin, together
with the rule that matters more than either: a term that found something is
never touched.
"""

from __future__ import annotations

import pytest

from app.core.database import SessionLocal
from app.domain.hub import service
from app.domain.hub.spelling import (
    closest_word,
    has_other_spelling,
    umlaut_variants,
)

from tests.test_hub_search import corpus  # noqa: F401 — fixture


class TestUmlautVariants:
    def test_writes_the_umlaut_out_and_back(self) -> None:
        assert umlaut_variants("muenchen") == ["münchen"]
        assert umlaut_variants("münchen") == ["muenchen"]
        assert umlaut_variants("grosshandel") == ["großhandel"]

    def test_a_word_without_either_spelling_has_no_variant(self) -> None:
        assert umlaut_variants("embedded") == []

    def test_variants_never_include_the_term_itself(self) -> None:
        for term in ("münchen", "muenchen", "strasse", "straße"):
            assert term not in umlaut_variants(term)


class TestHasOtherSpelling:
    """Which searches are worth the extra probes at all."""

    def test_a_word_with_a_written_out_umlaut_is_worth_checking(self) -> None:
        assert has_other_spelling("muenchen")
        assert has_other_spelling("embedded koeln")
        assert has_other_spelling("grosshandel")

    def test_an_ordinary_word_keeps_the_fast_path(self) -> None:
        assert not has_other_spelling("embedded")
        assert not has_other_spelling("sap berater")
        assert not has_other_spelling(None)

    def test_a_fragment_too_short_to_be_a_word_does_not_count(self) -> None:
        # "neue" → "neü" is 3 characters and is dropped, so a search for new
        # roles does not pay for a lookup that can never help.
        assert not has_other_spelling("neue")


class TestClosestWord:
    def test_finds_the_word_inside_a_title(self) -> None:
        titles = ["Embedded Software Entwickler (m/w/d)", "Pflegefachkraft"]
        assert closest_word("embeded", titles) == "embedded"
        assert closest_word("pflegefachkaft", titles) == "pflegefachkraft"

    def test_refuses_a_word_that_is_merely_adjacent(self) -> None:
        # "sap" and "saft" are one edit apart and mean nothing to each other.
        assert closest_word("sap", ["Saft Produktionshelfer"]) is None

    def test_never_hands_back_the_typo_itself(self) -> None:
        # The corpus carries other people's typos: two of 360,126 ads spell it
        # "Pflegefachkaft", and they are what a trigram lookup returns first.
        titles = ["Pflegefachkaft (m/w/d) Tagesklinik", "Pflegefachkraft w/m/d"]
        assert closest_word("pflegefachkaft", titles) == "pflegefachkraft"

    def test_returns_none_when_nothing_is_close(self) -> None:
        assert closest_word("zzzznomatch", ["Embedded Software Entwickler"]) is None


@pytest.mark.usefixtures("corpus")
class TestResolveQuery:
    async def test_an_umlaut_typed_out_still_finds_the_city(self) -> None:
        async with SessionLocal() as s:
            q, corrections = await service.resolve_query(s, "koeln")
            assert q == "köln"
            assert corrections == [{"from": "koeln", "to": "köln"}]
            assert len(await service.search_employers(s, q=q)) == 1

    async def test_a_term_that_matches_is_left_alone(self) -> None:
        async with SessionLocal() as s:
            for term in ("embedded", "pflegefachkraft", "köln"):
                assert await service.resolve_query(s, term) == (term, [])

    async def test_a_term_nothing_can_rescue_stays_as_typed(self) -> None:
        async with SessionLocal() as s:
            assert await service.resolve_query(s, "zzzznomatch") == ("zzzznomatch", [])
            assert await service.search_employers(s, q="zzzznomatch") == []

    async def test_only_the_broken_word_of_a_phrase_is_rewritten(self) -> None:
        async with SessionLocal() as s:
            q, corrections = await service.resolve_query(s, "embedded koeln")
            assert q == "embedded köln"
            assert [c["from"] for c in corrections] == ["koeln"]

    async def test_short_words_are_never_guessed_at(self) -> None:
        # Three letters are too few to be sure what was meant, and the corpus
        # is full of three-letter words that are one edit from each other.
        async with SessionLocal() as s:
            assert await service.resolve_query(s, "sap") == ("sap", [])

    async def test_an_empty_query_is_passed_through(self) -> None:
        async with SessionLocal() as s:
            assert await service.resolve_query(s, None) == (None, [])
            assert await service.resolve_query(s, "   ") == ("   ", [])


@pytest.mark.usefixtures("corpus")
class TestWhatIsLeftAlone:
    """The rewrite's value is in what it refuses to touch."""

    async def test_a_working_term_is_never_second_guessed(self) -> None:
        # "Verkäufer" works; its ASCII twin must not replace it, and vice
        # versa — both spellings reach the corpus here.
        async with SessionLocal() as s:
            for term in ("verkäufer", "stuttgart", "klinikum"):
                assert await service.resolve_query(s, term) == (term, [])

    async def test_a_too_short_variant_is_refused(self) -> None:
        # Not every "ue" is an umlaut: "neue" yields "neü", and the live
        # corpus has a worse one — a two-letter fragment like "nü" reaches
        # every Nürnberg employer. Anything under four characters is dropped
        # before it can answer a question about new roles with Franconia.
        assert umlaut_variants("neue") == ["neü"]
        async with SessionLocal() as s:
            assert await service.resolve_query(s, "neue") == ("neue", [])


@pytest.mark.usefixtures("corpus")
class TestSearchEndpoint:
    """The route decides WHEN to correct; the service only decides what to."""

    async def _search(self, **params):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.get("/api/v1/hub/search", params=params)
            assert r.status_code == 200, r.text
            return r.json()

    async def test_a_thin_answer_is_retried_and_the_retry_is_declared(self) -> None:
        body = await self._search(q="koeln")
        assert body["total"] == 1
        assert body["corrections"] == [{"from": "koeln", "to": "köln"}]
        assert body["items"][0]["name"].startswith("Netto")

    async def test_a_good_answer_is_never_corrected(self) -> None:
        body = await self._search(q="embedded")
        assert body["total"] == 1
        assert body["corrections"] == []

    async def test_the_reader_can_refuse_the_correction(self) -> None:
        # "trotzdem nach „koeln" suchen" — the literal query must stay
        # reachable, or the rescue becomes a cage.
        body = await self._search(q="koeln", correct="false")
        assert body["corrections"] == []
        assert body["total"] == 0


@pytest.mark.usefixtures("corpus")
class TestWhenTheEndpointChecks:
    """A thin answer is not the only failure — a confident wrong one counts."""

    async def _total(self, **params) -> dict:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.get("/api/v1/hub/search", params=params)
            assert r.status_code == 200, r.text
            return r.json()

    async def test_an_umlaut_term_is_rechecked_even_with_results(self) -> None:
        # Measured live: "muenchen" returns 298 employers with München in
        # their NAME and misses the 2,973 in the city. Here the fixture's
        # Netto Köln stands in for that shape — "koeln" finds the company
        # through its normalized name, so the answer is not thin, and the
        # correction still has to happen.
        body = await self._total(q="koeln")
        assert body["corrections"] == [{"from": "koeln", "to": "köln"}]

    async def test_a_correction_that_finds_less_is_discarded(self) -> None:
        # The retry only wins when it is actually better; otherwise the
        # reader is told nothing and keeps their own words.
        body = await self._total(q="embedded")
        assert body["corrections"] == []
        assert body["total"] == 1
