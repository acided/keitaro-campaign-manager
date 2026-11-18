"""API tests run against a real Postgres database `kcm_test` (docker compose up -d db)
and an in-memory fake of Keitaro."""

import asyncio
import copy
import os

import asyncpg
import httpx
import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import get_keitaro
from app.db import get_session
from app.keitaro import KeitaroError
from app.main import app
from app.models import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://kcm:kcm@127.0.0.1:5432/kcm_test"
)

OURS, FOREIGN = 100, 200
GEO_STREAM, OFFER_STREAM = 1, 2


def keitaro_offer(offer_id: int, share: int, state: str = "active") -> dict:
    return {"offer_id": offer_id, "share": share, "state": state}


class FakeKeitaro:
    """Keitaro with one campaign of ours (redirect stream + 3 offers 34/33/33) and a foreign one."""

    def __init__(self) -> None:
        self.campaigns_ = {
            OURS: {"id": OURS, "name": "test_kochkurov_demo"},
            FOREIGN: {"id": FOREIGN, "name": "someone_else"},
        }
        self.streams = {
            OURS: [
                {"id": GEO_STREAM, "name": "Geo -> google", "position": 1, "schema": "redirect", "offers": []},
                {"id": OFFER_STREAM, "name": "Offers", "position": 2, "schema": "landings",
                 "offers": [keitaro_offer(11, 34), keitaro_offer(12, 33), keitaro_offer(13, 33)]},
            ],
            FOREIGN: [],
        }  # fmt: skip
        self.catalog = [{"id": i, "name": f"{i} Offer {i}", "state": "active"} for i in range(11, 16)]
        self.domains_ = [{"id": 1813, "name": "kylovoa.com"}]
        self.groups = [{"id": 1, "name": "Other"}, {"id": 10332, "name": "FORTESTS"}]
        self.sources = [{"id": 836, "name": "FORTESTS"}]

        self.streams_read: list[int] = []
        self.pushes: list[tuple[int, list[dict]]] = []
        self.created: list[tuple[str, dict]] = []  # ("campaign" | "stream", payload)
        self.deleted: list[int] = []
        self.next_id = 300

        self.fail_push = False
        self.fail_stream: int | None = None  # 1-based number of the create_stream call to fail
        self.fail_delete = False

    async def offers(self):
        return self.catalog

    async def domains(self):
        return self.domains_

    async def campaign_groups(self):
        return self.groups

    async def traffic_sources(self):
        return self.sources

    async def create_campaign(self, payload):
        self.created.append(("campaign", payload))
        campaign_id, self.next_id = self.next_id, self.next_id + 1
        self.campaigns_[campaign_id] = {"id": campaign_id, "name": payload["name"]}
        self.streams[campaign_id] = []
        return {"id": campaign_id, **payload}

    async def create_stream(self, payload):
        self.created.append(("stream", payload))
        if self.fail_stream == sum(kind == "stream" for kind, _ in self.created):
            raise KeitaroError("Keitaro POST /streams failed (422): filters: invalid")
        stream_id, self.next_id = self.next_id, self.next_id + 1
        self.streams[payload["campaign_id"]].append({
            "id": stream_id, "name": payload["name"], "position": payload["position"],
            "schema": payload["schema"], "offers": copy.deepcopy(payload.get("offers", [])),
        })  # fmt: skip
        return {"id": stream_id}

    async def delete_campaign(self, campaign_id):
        if self.fail_delete:
            raise KeitaroError(f"Keitaro DELETE /campaigns/{campaign_id} failed (500): boom")
        self.deleted.append(campaign_id)
        del self.campaigns_[campaign_id], self.streams[campaign_id]

    async def campaigns(self):
        return list(self.campaigns_.values())

    async def campaign(self, campaign_id):
        if campaign_id not in self.campaigns_:
            raise KeitaroError(f"Keitaro GET /campaigns/{campaign_id} failed (404): Not found")
        return self.campaigns_[campaign_id]

    async def campaign_streams(self, campaign_id):
        self.streams_read.append(campaign_id)
        return copy.deepcopy(self.streams[campaign_id])

    async def set_stream_offers(self, stream_id, offers):
        if self.fail_push:
            raise KeitaroError(f"Keitaro PUT /streams/{stream_id} failed (500): boom")
        self.pushes.append((stream_id, offers))
        for stream in (s for streams in self.streams.values() for s in streams):
            if stream["id"] == stream_id:
                stream["offers"] = copy.deepcopy(offers)
        return {}


@pytest.fixture(scope="session")
def database_url() -> str:
    """Create the test database once and build the schema from the models."""

    async def prepare() -> None:
        url = make_url(TEST_DATABASE_URL)
        admin_dsn = url.set(drivername="postgresql", database="postgres").render_as_string(False)
        admin = await asyncpg.connect(admin_dsn)
        try:
            if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", url.database):
                await admin.execute(f'CREATE DATABASE "{url.database}"')
        finally:
            await admin.close()

        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(prepare())
    return TEST_DATABASE_URL


@pytest.fixture
def keitaro() -> FakeKeitaro:
    return FakeKeitaro()


@pytest.fixture
async def client(database_url, keitaro):
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE campaigns, streams, stream_offers RESTART IDENTITY CASCADE"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def test_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_keitaro] = lambda: keitaro
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()
