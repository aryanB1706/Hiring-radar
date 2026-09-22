from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import SourceKind
from app.db.models import Post, Source
from app.db.session import get_session
from app.main import create_app
from app.schemas.captures import MAX_CSV_BYTES, MAX_CSV_ROWS


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def use_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = use_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def stored(session: AsyncSession, url: str) -> tuple[Post, Source]:
    row = (await session.execute(select(Post, Source).join(Source).where(Post.url == url))).one()
    return row[0], row[1]


async def test_capture_stores_a_cleaned_post_under_manual_paste(
    client: AsyncClient, session: AsyncSession
) -> None:
    url = "https://www.linkedin.com/posts/acme-hiring-1"
    response = await client.post(
        "/api/captures",
        json={
            "url": url,
            "text": "<p>Hiring a <b>Python</b> dev</p><p>DM me</p>",
            "author_handle": "acme",
        },
    )

    assert response.status_code == 201
    assert response.json() == {"status": "inserted"}
    post, source = await stored(session, url)
    assert post.raw_text == "Hiring a Python dev\n\nDM me"
    assert (post.author_handle, source.kind) == ("acme", SourceKind.MANUAL_PASTE)


async def test_capture_hinted_as_linkedin_goes_to_the_linkedin_capture_source(
    client: AsyncClient, session: AsyncSession
) -> None:
    url = "https://www.linkedin.com/posts/x-2"
    response = await client.post(
        "/api/captures",
        json={"url": url, "text": "We are hiring", "source_hint": "linkedin_user_capture"},
    )
    assert response.status_code == 201
    assert (await stored(session, url))[1].kind == SourceKind.LINKEDIN_USER_CAPTURE


async def test_capturing_the_same_link_or_text_again_reports_duplicate(client: AsyncClient) -> None:
    body = {"url": "https://example.com/p/1", "text": "Need a freelancer"}
    assert (await client.post("/api/captures", json=body)).json() == {"status": "inserted"}
    assert (await client.post("/api/captures", json=body)).json() == {"status": "duplicate"}
    same_text = {"url": "https://example.com/p/2", "text": "NEED a  freelancer"}
    assert (await client.post("/api/captures", json=same_text)).json() == {"status": "duplicate"}


@pytest.mark.parametrize(
    "body",
    [
        {"url": "https://example.com/p"},  # no text
        {"text": "hello"},  # no url
        {"url": "https://example.com/p", "text": ""},
        {"url": "https://example.com/p", "text": "<p>  </p>"},  # nothing left after stripping HTML
        {"url": "https://example.com/p", "text": "x" * 20_001},
        {"url": "not a url", "text": "hello"},
        {"url": "javascript:alert(1)", "text": "hello"},
        {"url": "https://example.com/" + "a" * 2100, "text": "hello"},
        {"url": "https://example.com/p", "text": "hello", "source_hint": "instagram"},
    ],
)
async def test_capture_rejects_invalid_input(client: AsyncClient, body: dict) -> None:
    assert (await client.post("/api/captures", json=body)).status_code == 422


def csv_body(*rows: str, header: str = "url,text,author_handle") -> bytes:
    return "\n".join([header, *rows]).encode()


async def test_csv_import_inserts_good_rows_and_reports_bad_ones(
    client: AsyncClient, session: AsyncSession
) -> None:
    body = csv_body(
        'https://example.com/a,"Hiring a dev, remote",alice',
        "https://example.com/b,Need a freelancer for a scraper,",
        "not-a-url,some text,",
        "https://example.com/c,   ,",
    )
    response = await client.post(
        "/api/captures/csv", content=body, headers={"content-type": "text/csv"}
    )

    assert response.status_code == 200
    out = response.json()
    assert (out["rows"], out["inserted"], out["skipped_duplicate"]) == (4, 2, 0)
    assert [r["row"] for r in out["rejected"]] == [3, 4]
    assert out["rejected"][0]["error"].startswith("url")
    post, source = await stored(session, "https://example.com/a")
    assert (post.raw_text, post.author_handle, source.kind) == (
        "Hiring a dev, remote",
        "alice",
        SourceKind.CSV_IMPORT,
    )


async def test_csv_import_twice_inserts_nothing_new(client: AsyncClient) -> None:
    body = csv_body("https://example.com/a,Hiring a dev,", "https://example.com/b,Need a designer,")
    await client.post("/api/captures/csv", content=body)
    again = (await client.post("/api/captures/csv", content=body)).json()
    assert (again["inserted"], again["skipped_duplicate"]) == (0, 2)


async def test_csv_needs_url_and_text_columns(client: AsyncClient) -> None:
    response = await client.post("/api/captures/csv", content=csv_body("a,b", header="link,body"))
    assert response.status_code == 422


async def test_csv_size_and_row_limits(client: AsyncClient) -> None:
    too_big = await client.post("/api/captures/csv", content=b"x" * (MAX_CSV_BYTES + 1))
    assert too_big.status_code == 413

    rows = [f"https://example.com/{i},post {i}," for i in range(MAX_CSV_ROWS + 1)]
    too_many = await client.post("/api/captures/csv", content=csv_body(*rows))
    assert too_many.status_code == 422


async def test_csv_that_is_not_utf8_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/captures/csv", content=b"url,text\n\xff\xfe,\xff")
    assert response.status_code == 422
