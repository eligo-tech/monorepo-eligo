"""The workspace's own icon in the cockpit header (ELI-55).

A second picture next to the cover-sheet logo: the header is dark and the
PDF is white, so one file cannot serve both. Per workspace, in the database
(memory: "no product config in Railway"). An SVG is accepted because that is
what agencies have, but it is rebuilt from an allow-list — only shapes and
fill rules survive; scripts, links, event handlers and foreign markup do not.
"""

from __future__ import annotations

import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.core.auth import RECRUITER, Actor, get_current_actor
from app.core.config import settings
from app.domain.presentation.service import InvalidLogo, sanitize_svg

TENANT = settings.default_tenant_id
API = "/api/v1"

ICON = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
    b"<defs><style>.cls-1 { fill: #fff; }</style></defs>"
    b'<path class="cls-1" d="M52.58,38.14h21.84v61.33h-12.39Z"/>'
    b'<rect class="cls-1" x="52.58" y="101.86" width="54.83" height="10.95"/>'
    b"</svg>"
)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
async def client():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


def test_a_clean_svg_keeps_its_shapes_and_its_fill_rule() -> None:
    out = sanitize_svg(ICON).decode()
    assert 'viewBox="0 0 160 160"' in out
    assert "M52.58,38.14h21.84v61.33h-12.39Z" in out
    assert ".cls-1 { fill: #fff; }" in out
    assert "<rect" in out


@pytest.mark.parametrize(
    "hostile",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><path d="M0 0h1"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1" onload="alert(1)"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        # A refused element goes with everything inside it.
        b'<a xlink:href="javascript:alert(1)"><path d="M9 9h1"/></a><path d="M0 0h1"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div>x</div></foreignObject>'
        b'<path d="M0 0h1"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(http://evil/x.css);</style>'
        b'<path d="M0 0h1"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1" style="fill:url(http://evil)"/></svg>',
    ],
)
def test_a_hostile_svg_loses_everything_but_its_shapes(hostile: bytes) -> None:
    out = sanitize_svg(hostile).decode().lower()
    for word in ("script", "onload", "javascript", "foreignobject", "href", "import", "url(", "<a"):
        assert word not in out
    assert 'd="m0 0h1"' in out


@pytest.mark.parametrize(
    "bad",
    [
        b"not xml",
        b"<html><body/></html>",
        b'<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>',  # nothing left
        # UTF-16 hides "<!ENTITY" from a byte search; only UTF-8 is read.
        pytest.param(
            '<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg" class="&x;">'
            '<path d="M0 0h1"/></svg>'.encode("utf-16"),
            id="utf16-entity",
        ),
        # Deep nesting is refused, not a 500.
        pytest.param(
            b'<svg xmlns="http://www.w3.org/2000/svg">' + b"<g>" * 2000 + b'<path d="M0 0h1"/>'
            + b"</g>" * 2000 + b"</svg>",
            id="deep-nesting",
        ),
    ],
)
def test_what_is_not_a_drawable_svg_is_refused(bad: bytes) -> None:
    with pytest.raises(InvalidLogo):
        sanitize_svg(bad)


async def test_the_header_icon_is_an_admins_and_is_served_cleaned(client) -> None:
    from app.main import app

    assert (await client.get(f"{API}/branding")).json()["has_header_icon"] is False
    assert (await client.get(f"{API}/branding/header-icon")).status_code == 404

    up = await client.put(
        f"{API}/branding/header-icon", files={"file": ("icon.svg", ICON, "image/svg+xml")}
    )
    assert up.status_code == 200 and up.json()["has_header_icon"] is True
    # The cover-sheet logo is a different slot and stays empty.
    assert up.json()["has_logo"] is False

    got = await client.get(f"{API}/branding/header-icon")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/svg+xml")
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in got.headers["content-security-policy"]
    assert "no-store" in got.headers["cache-control"]
    assert b"M52.58,38.14" in got.content and b"<?xml" not in got.content

    png = await client.put(
        f"{API}/branding/header-icon", files={"file": ("icon.png", _png(), "image/png")}
    )
    assert png.status_code == 200
    assert (await client.get(f"{API}/branding/header-icon")).content == _png()
    bad = await client.put(
        f"{API}/branding/header-icon", files={"file": ("icon.gif", b"GIF89a", "image/gif")}
    )
    assert bad.status_code == 422

    app.dependency_overrides[get_current_actor] = lambda: Actor(
        tenant_id=TENANT, user_id="user_rec", name="Rita", role=RECRUITER, role_known=True
    )
    assert (
        await client.put(
            f"{API}/branding/header-icon", files={"file": ("icon.svg", ICON, "image/svg+xml")}
        )
    ).status_code == 403
    assert (await client.delete(f"{API}/branding/header-icon")).status_code == 403
    # Everyone sees their workspace's icon.
    assert (await client.get(f"{API}/branding/header-icon")).status_code == 200
    app.dependency_overrides.clear()

    assert (await client.delete(f"{API}/branding/header-icon")).status_code == 204
    assert (await client.get(f"{API}/branding")).json()["has_header_icon"] is False


async def test_another_workspace_does_not_see_the_icon(client) -> None:
    from app.main import app

    await client.put(
        f"{API}/branding/header-icon", files={"file": ("icon.svg", ICON, "image/svg+xml")}
    )
    other = uuid.uuid4()
    app.dependency_overrides[get_current_actor] = lambda: Actor(
        tenant_id=other, user_id="user_x", name="X", role=RECRUITER, role_known=True
    )
    assert (await client.get(f"{API}/branding")).json()["has_header_icon"] is False
    assert (await client.get(f"{API}/branding/header-icon")).status_code == 404
