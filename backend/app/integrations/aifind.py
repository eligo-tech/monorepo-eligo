"""aiFind (panam) — importing a recruiter's OWN book of business.

Where this data lands is the whole design question, and it is not the hub.

`hub_*` is a SHARED corpus of public facts about the outside world: every
workspace reads the same Bundesagentur postings because they are the same for
everyone. These 37 jobs are the opposite — they are one workspace's client
mandates, naming its clients and the people it sells to. Putting them in the
shared corpus would publish one customer's book of business to every other
customer. So the import writes tenant-scoped `companies`, `managers` and `jobs`,
and nothing here touches a `hub_` table.

The module splits the way `hub/adapters` do and for the same reason: a pure
`parse_jobs` over a captured payload, and a thin client that does the network.
CI exercises the real parser with no network and no credentials.

Auth is the awkward part and worth recording. `aifind-ui` is a public SPA client
with direct access grants DISABLED — the correct posture for a browser client,
and it means a password grant returns `unauthorized_client`. The way in is the
flow a browser uses: authorization code + PKCE, driving the Keycloak login form.
That is why this needs an email and a password rather than an API key, and why
it is more code than an API client normally would be.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import html
import re
import secrets
import urllib.parse

import httpx

ISSUER = "https://kc.apps.aifind.de/auth/realms/panam"
CLIENT_ID = "aifind-ui"
REDIRECT_URI = "https://panam.apps.aifind.de/dashboard"
GRAPHQL_URL = "https://panam.apps.aifind.de/api/graphql"

#: Exactly the queries the app's own list screens issue, harvested from the
#: running client. Apollo introspection is DISABLED on their server, so a schema
#: cannot be read — these shapes can only be extended by observing the app, never
#: by guessing field names. Each is paired with the variables the app sends.
#:
#: What the source exposes per entity is thinner than its detail screens show:
#: the lists are lists. Anything richer (a candidate's CV, a job description)
#: needs the per-record query, which is a separate harvesting exercise.
QUERIES: dict[str, str] = {
    "companies": """
query companies($q: String, $size: Int!, $from: Int!, $sort: Sort) {
  companies(q: $q, size: $size, from: $from, sort: $sort) {
    total
    hits { id name added_by owner }
  }
}
""",
    "managers": """
query managers($q: String, $size: Int!, $from: Int!, $sort: Sort) {
  managers(q: $q, size: $size, from: $from, sort: $sort) {
    total
    hits { id first_name last_name job_title company { id name } added_by owner }
  }
}
""",
    "jobs": """
query jobs($q: String, $size: Int!, $from: Int!, $sort: Sort, $isOpen: Boolean, $onlySelf: Boolean) {
  jobs(q: $q, size: $size, from: $from, sort: $sort, isOpen: $isOpen, onlySelf: $onlySelf) {
    total
    hits {
      id title priority isOpen employment added_by owner
      manager { id first_name last_name }
      company { id name }
    }
  }
}
""",
    "candidates": """
query candidates($q: String, $size: Int!, $from: Int!, $sort: Sort) {
  candidates(q: $q, size: $size, from: $from, sort: $sort) {
    total
    hits { id first_name last_name job_title employment added_by owner address { zip } }
  }
}
""",
}

#: The variables each list screen sends, minus paging. `onlySelf: False` matters:
#: the app defaults to the signed-in user's own records, and an import that
#: inherits that default silently misses every colleague's book.
DEFAULT_VARIABLES: dict[str, dict] = {
    "companies": {"sort": {"prop": "name", "dir": "ASC"}},
    "managers": {"sort": {"prop": "last_name", "dir": "ASC"}},
    "jobs": {
        "sort": {"prop": "createdAt", "dir": "DESC"},
        "isOpen": None,
        "onlySelf": False,
    },
    "candidates": {"sort": {"prop": "last_name", "dir": "ASC"}},
}

# `interviews` and `deals` are deliberately NOT imported yet. They exist in the
# source (1 and 5 records) and their queries were captured, but they describe
# process state — an interview belongs with `applications`, a deal with revenue
# reporting — and mapping process onto a model that does not yet have a home for
# it would invent semantics rather than import data.


@dataclasses.dataclass(frozen=True)
class AiFindManager:
    external_id: str
    full_name: str
    job_title: str | None = None
    company_external_id: str | None = None


@dataclasses.dataclass(frozen=True)
class AiFindCompany:
    external_id: str
    name: str


@dataclasses.dataclass(frozen=True)
class AiFindCandidate:
    external_id: str
    full_name: str
    job_title: str | None = None
    employment: str | None = None
    postal_code: str | None = None


@dataclasses.dataclass(frozen=True)
class AiFindJob:
    """One mandate, normalized. Company and manager are optional by type.

    Every one of the 37 open records carries both, but a mandate logged before
    the client contact is known is an ordinary state in a CRM, and an importer
    that assumes otherwise breaks on the first one.
    """

    external_id: str
    title: str
    is_open: bool
    priority: str | None
    employment: str | None
    company: AiFindCompany | None
    manager: AiFindManager | None
    owner: str | None


def _name(first: object, last: object) -> str:
    """Join a padded name pair into one squeezed string.

    The source returns "Stefan " / "Graf". Concatenated naively that is
    "Stefan  Graf", and on the next import the same person arrives as a second
    manager whose only difference is a double space.
    """
    return " ".join(f"{first or ''} {last or ''}".split())


def _scalar(value: object) -> str | None:
    """One string from a field the source types inconsistently.

    `employment` comes back as a scalar on jobs ("Permanent") and as a LIST on
    candidates (["Contract", "Permanent"]) — a candidate can be open to several
    arrangements, a mandate is one. Assuming the scalar shape drove a DataError
    on the first real import, 391 candidates in.

    Joined rather than truncated to the first: "open to contract or permanent"
    is the fact, and dropping half of it silently narrows a candidate's
    availability.
    """
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return ", ".join(parts) or None
    return str(value).strip() or None


def _hits(payload: dict, operation: str) -> list[dict]:
    return ((payload.get("data") or {}).get(operation) or {}).get("hits") or []


def parse_companies(payload: dict) -> list[AiFindCompany]:
    out = []
    for hit in _hits(payload, "companies"):
        name = " ".join(str(hit.get("name") or "").split())
        if hit.get("id") and name:
            out.append(AiFindCompany(external_id=str(hit["id"]), name=name))
    return out


def parse_managers(payload: dict) -> list[AiFindManager]:
    out = []
    for hit in _hits(payload, "managers"):
        full = _name(hit.get("first_name"), hit.get("last_name"))
        if not hit.get("id") or not full:
            # A person with no name is not a contact. Importing one would put an
            # unidentifiable natural person into the record.
            continue
        company = hit.get("company") or {}
        out.append(
            AiFindManager(
                external_id=str(hit["id"]),
                full_name=full,
                job_title=_scalar(hit.get("job_title")),
                company_external_id=(
                    str(company["id"]) if company.get("id") else None
                ),
            )
        )
    return out


def parse_candidates(payload: dict) -> list[AiFindCandidate]:
    out = []
    for hit in _hits(payload, "candidates"):
        full = _name(hit.get("first_name"), hit.get("last_name"))
        if not hit.get("id") or not full:
            continue
        address = hit.get("address") or {}
        out.append(
            AiFindCandidate(
                external_id=str(hit["id"]),
                full_name=full,
                job_title=_scalar(hit.get("job_title")),
                employment=_scalar(hit.get("employment")),
                postal_code=_scalar(address.get("zip")),
            )
        )
    return out


def parse_jobs(payload: dict) -> list[AiFindJob]:
    """GraphQL payload → normalized mandates. Pure: no network, no session."""
    jobs: list[AiFindJob] = []
    for hit in _hits(payload, "jobs"):
        if not hit.get("id") or not (hit.get("title") or "").strip():
            # An untitled mandate is not a mandate. Skipping beats importing a
            # row nobody can identify in a list.
            continue
        company = hit.get("company") or {}
        manager = hit.get("manager") or {}
        manager_name = _name(manager.get("first_name"), manager.get("last_name"))
        jobs.append(
            AiFindJob(
                external_id=str(hit["id"]),
                title=" ".join(str(hit["title"]).split()),
                is_open=bool(hit.get("isOpen")),
                priority=_scalar(hit.get("priority")),
                employment=_scalar(hit.get("employment")),
                company=(
                    AiFindCompany(
                        external_id=str(company["id"]),
                        name=" ".join(str(company.get("name") or "").split()),
                    )
                    if company.get("id") and company.get("name")
                    else None
                ),
                manager=(
                    AiFindManager(
                        external_id=str(manager["id"]),
                        full_name=manager_name,
                        company_external_id=(
                            str(company["id"]) if company.get("id") else None
                        ),
                    )
                    if manager.get("id") and manager_name
                    else None
                ),
                owner=(hit.get("owner") or hit.get("added_by") or None),
            )
        )
    return jobs


PARSERS = {
    "companies": parse_companies,
    "managers": parse_managers,
    "jobs": parse_jobs,
    "candidates": parse_candidates,
}


async def fetch_access_token(
    client: httpx.AsyncClient, *, username: str, password: str
) -> str:
    """Authorization code + PKCE against Keycloak, driving the login form.

    A password grant is refused — `aifind-ui` is a public client with direct
    access grants off — so this walks the same path a browser does.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    page = await client.get(
        f"{ISSUER}/protocol/openid-connect/auth",
        params={
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "openid profile email",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_hex(8),
            "nonce": secrets.token_hex(8),
        },
    )
    page.raise_for_status()
    form = re.search(r'action="([^"]+)"', page.text)
    if not form:
        raise RuntimeError("Keycloak login form not found — the flow has changed")

    posted = await client.post(
        html.unescape(form.group(1)),
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    location = posted.headers.get("location", "")
    if "code=" not in location:
        # Never echo the response body: a failed Keycloak login renders the form
        # again, and the form contains the submitted username.
        raise RuntimeError(
            f"aiFind login did not return an authorization code "
            f"(HTTP {posted.status_code}) — check AI_FIND_EMAIL / AI_FIND_PWD"
        )
    code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)["code"][0]

    token = await client.post(
        f"{ISSUER}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    token.raise_for_status()
    return token.json()["access_token"]


async def fetch_all(
    client: httpx.AsyncClient,
    *,
    token: str,
    operation: str,
    page_size: int = 200,
) -> list:
    """Every record of one entity, paged, parsed.

    Pages rather than asking for everything at once: `managers` is 650 rows and
    a source that answers a size=1000 request today may cap it tomorrow. The
    loop stops on `total`, not on an empty page, so a short page caused by a
    server-side cap does not look like the end of the data.
    """
    parser = PARSERS[operation]
    variables = {"q": "", **DEFAULT_VARIABLES[operation]}
    records: list = []
    total = None
    offset = 0
    while total is None or offset < total:
        response = await client.post(
            GRAPHQL_URL,
            headers={"authorization": f"Bearer {token}"},
            json={
                "operationName": operation,
                "query": QUERIES[operation],
                "variables": {**variables, "from": offset, "size": page_size},
            },
        )
        response.raise_for_status()
        body = response.json()
        if body.get("errors"):
            raise RuntimeError(
                f"aiFind {operation}: {body['errors'][0].get('message')}"
            )
        node = (body.get("data") or {}).get(operation) or {}
        total = node.get("total", 0)
        page = parser(body)
        records.extend(page)
        got = len(node.get("hits") or [])
        if got == 0:
            break
        offset += got
    return records
