import json
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.datalayer import news, news_sources
from backend.scoring.composite import AI_CAP, score_intent
from backend.core.models import Intent, Side

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
NAMES = {"BANKINDIA": "Bank of India", "RELIANCE": "Reliance Industries", "IOC": "Indian Oil Corporation", "TCS": "Tata Consultancy Services",
         "TATASTEEL": "Tata Steel"}
SECTOR_OF = {"RELIANCE": "Oil Gas & Consumable Fuels", "IOC": "Oil Gas & Consumable Fuels",
             "TCS": "Information Technology", "TATASTEEL": "Metals & Mining"}


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None, nx=False, **_):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)

    async def incrby(self, key, n):
        self.data[key] = int(self.data.get(key, 0)) + n

    async def expire(self, key, seconds):
        pass

    def pipeline(self, transaction=False):
        redis = self

        class _Pipe:
            async def __aenter__(self):
                self.ops = []
                return self

            async def __aexit__(self, *exc):
                return False

            def set(self, *a, **kw):
                self.ops.append((a, kw))

            async def execute(self):
                for a, kw in self.ops:
                    await redis.set(*a, **kw)

        return _Pipe()


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


@pytest.fixture(autouse=True)
def sectors(monkeypatch):
    monkeypatch.setattr(news_sources, "sectors", lambda: sorted(set(SECTOR_OF.values())))


def _item(title, feed="et_markets", symbols=(), published=NOW, scope="MARKET"):
    return {"title": title, "url": "https://x/" + title, "source": "ET", "published_at": published,
            "content": "", "feed": feed, "scope_hint": scope, "symbols": list(symbols)}


def _llm(monkeypatch, *responses):
    calls = []
    replies = list(responses)

    async def complete(system, user):
        calls.append(user)
        return json.dumps(replies.pop(0))

    monkeypatch.setattr(news, "_fast", complete)
    monkeypatch.setattr(news, "_deep", complete)
    return calls


def test_tagging_finds_names_unique_first_words_and_tickers_only():
    aliases = news.build_aliases(NAMES)
    assert news.tag("Reliance shares jump after Jio deal", aliases) == ["RELIANCE"]
    assert news.tag("TCS wins a $1bn order", aliases) == ["TCS"]
    assert news.tag("Tata group plans new fab", aliases) == []          # "Tata" is shared: no guess
    assert news.tag("Indian equities fall", aliases) == []              # generic first word
    assert news.tag("tcs is not a ticker in lower case", aliases) == []
    assert news.tag("Reserve Bank of India holds rates", aliases) == []
    assert news.tag("Bank of India raises MCLR", aliases) == ["BANKINDIA"]


def test_rss_and_nse_parsing():
    xml = b"""<rss><channel>
      <item><title>Brent jumps 6%</title><link>https://a</link><pubDate>Mon, 05 Oct 2026 07:00:00 GMT</pubDate>
            <description>&lt;p&gt;Oil &lt;b&gt;up&lt;/b&gt;&lt;/p&gt;</description></item>
      <item><title>Old story</title><pubDate>Mon, 01 Jan 2024 07:00:00 GMT</pubDate></item>
    </channel></rss>"""
    [item] = news_sources.parse_rss(xml, "cnbc_world", "GLOBAL")
    assert item["title"] == "Brent jumps 6%" and item["content"] == "Oil up"
    assert item["published_at"] == datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)

    rows = [{"symbol": "TCS", "desc": "Outcome of Board Meeting", "sm_name": "TCS Ltd", "sort_date": "2026-10-05 13:30:00",
             "attchmntText": "Dividend declared", "attchmntFile": "https://f"},
            {"symbol": "TCS", "desc": "Copy of Newspaper Publication", "sort_date": "2026-10-05 13:30:00"},
            {"symbol": "ZZZ", "desc": "Outcome of Board Meeting", "sort_date": "2026-10-05 13:30:00"}]
    [filing] = news_sources.parse_nse(rows, {"TCS"})
    assert filing["symbols"] == ["TCS"] and filing["published_at"] == datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


async def test_store_dedupes_across_sources_and_filings_skip_triage(mongo):
    aliases = news.build_aliases(NAMES)
    assert await news.store(mongo, [_item("Reliance hits record - ET"), _item("Reliance hits record - Mint", feed="mint")],
                            aliases, now=NOW) == 1
    doc = await mongo[news.COLLECTION].find_one()
    assert doc["symbols"] == ["RELIANCE"] and sorted(doc["feeds"]) == ["et_markets", "mint"]
    assert doc["status"] == news.NEW and doc["expire_at"] == NOW + news.IRRELEVANT_TTL

    await news.store(mongo, [_item("TCS: Outcome of Board Meeting", feed="nse", symbols=["TCS"], scope="COMPANY")],
                     aliases, now=NOW)
    filing = await mongo[news.COLLECTION].find_one({"feeds": "nse"})
    assert filing["status"] == news.TRIAGED and filing["expire_at"] == NOW + news.RELEVANT_TTL


async def test_triage_keeps_relevant_drops_noise_and_retries_unanswered(mongo, monkeypatch):
    await news.store(mongo, [_item("Fed signals hike"), _item("Cricket final tonight"), _item("Gold rate today")],
                     [], now=NOW)
    _llm(monkeypatch, {"items": [
        {"index": 0, "relevant": True, "scope": "GLOBAL", "themes": ["rates"], "region": "US"},
        {"index": 1, "relevant": False}]})
    await news.triage(mongo, now=NOW)
    by_title = {d["title"]: d async for d in mongo[news.COLLECTION].find()}
    assert by_title["Fed signals hike"]["status"] == news.TRIAGED
    assert by_title["Fed signals hike"]["expire_at"] == NOW + news.RELEVANT_TTL
    assert by_title["Cricket final tonight"]["status"] == news.IRRELEVANT
    assert by_title["Gold rate today"]["status"] == news.NEW and by_title["Gold rate today"]["attempts"] == 1


async def test_scoring_validates_targets_and_flags_material(mongo, monkeypatch):
    await news.store(mongo, [_item("Brent jumps 8% after Gulf strike", symbols=["IOC"], scope="GLOBAL")], [], now=NOW)
    await mongo[news.COLLECTION].update_many({}, {"$set": {"status": news.TRIAGED, "scope": "GLOBAL"}})
    calls = _llm(monkeypatch, {"items": [{"index": 0, "event": "Brent spikes", "impacts": [
        {"type": "market", "target": "INDIA", "direction": -0.4, "impact": 6},
        {"type": "sector", "target": "Oil Gas & Consumable Fuels", "direction": -0.6, "impact": 7},
        {"type": "sector", "target": "Airlines", "direction": -0.8, "impact": 7},        # not a known sector
        {"type": "symbol", "target": "ioc", "direction": -3.0, "impact": 12},          # clamped
        {"type": "symbol", "target": "NOTREAL", "direction": 1.0, "impact": 9},
    ]}]})
    assert await news.score(mongo, NAMES, SECTOR_OF, set(), calls=1, now=NOW) == 1
    assert "IOC (Indian Oil Corporation, Oil Gas & Consumable Fuels)" in calls[0]
    doc = await mongo[news.COLLECTION].find_one()
    assert doc["status"] == news.SCORED and doc["material"] is True and doc["event"] == "Brent spikes"
    assert [(i["type"], i["target"]) for i in doc["impacts"]] == [
        ("market", "INDIA"), ("sector", "Oil Gas & Consumable Fuels"), ("symbol", "IOC")]
    assert doc["impacts"][2]["direction"] == -1.0 and doc["impacts"][2]["impact"] == 10.0


async def test_old_unscored_items_go_stale_without_an_llm_call(mongo, monkeypatch):
    await news.store(mongo, [_item("Week-old story", published=NOW - timedelta(days=5))], [], now=NOW)
    await mongo[news.COLLECTION].update_many({}, {"$set": {"status": news.TRIAGED}})
    calls = _llm(monkeypatch)
    assert await news.score(mongo, NAMES, SECTOR_OF, set(), calls=1, now=NOW) == 0
    assert calls == [] and (await mongo[news.COLLECTION].find_one())["status"] == news.STALE


async def test_aggregate_blends_company_sector_and_market(mongo):
    def scored(title, impacts):
        return {"_id": title, "title": title, "status": news.SCORED, "published_at": NOW - timedelta(hours=1),
                "event": title, "impacts": impacts}

    await mongo[news.COLLECTION].insert_many([
        scored("crude spike", [{"type": "market", "target": "INDIA", "direction": -0.5, "impact": 6},
                               {"type": "sector", "target": "Oil Gas & Consumable Fuels", "direction": -0.8, "impact": 7}]),
        scored("TCS big win", [{"type": "symbol", "target": "TCS", "direction": 0.9, "impact": 8}]),
    ])
    redis = FakeRedis()
    out = await news.aggregate(mongo, redis, NAMES, SECTOR_OF, now=NOW)

    # IOC has no company news: its sector and the market still move it.
    assert out["symbols"]["IOC"] == pytest.approx(0.25 * -0.8 + 0.15 * -0.5)
    assert out["symbols"]["TCS"] == pytest.approx(0.6 * 0.9 + 0.15 * -0.5)
    assert float(redis.data["sentiment:IOC"]) == pytest.approx(-0.275)
    assert json.loads(redis.data["sector_sentiment:Oil Gas & Consumable Fuels"])["score"] == pytest.approx(-0.8)
    verdict = json.loads(redis.data["analyst_verdict:TCS"])
    assert verdict["label"] == "bullish" and verdict["impact_score"] == 8 and verdict["top_reason"] == "TCS big win"
    assert "analyst_verdict:IOC" not in redis.data  # no company news, no verdict

    # Still one capped ai_score: a maximal blend moves conviction by at most AI_CAP.
    intent = Intent(symbol="TCS", side=Side.BUY, strength=0.5, reason_codes=["x"])
    assert score_intent(intent, 1.0).final - score_intent(intent, -1.0).final == pytest.approx(AI_CAP)


async def test_analysis_reads_the_layer_and_reuses_an_up_to_date_note(mongo, monkeypatch):
    from backend.database import db
    from backend.datalayer import analysis
    from backend.components.analyst import agent

    redis = FakeRedis()
    monkeypatch.setattr(db, "db", mongo)
    monkeypatch.setattr(db, "redis", redis)
    monkeypatch.setattr(news, "followed", lambda _db: _async((NAMES, SECTOR_OF)))
    redis.data["ingest:heartbeat:news_process"] = str(int(datetime.now(timezone.utc).timestamp()))
    redis.data["sentiment:TCS"] = "0.465"
    await mongo[news.COLLECTION].insert_one({
        "_id": "a", "title": "TCS big win", "status": news.SCORED, "published_at": datetime.now(timezone.utc),
        "event": "order", "impacts": [{"type": "symbol", "target": "TCS", "direction": 0.9, "impact": 8}]})
    reports = []

    async def report(**values):
        reports.append(values)
        return "Bullish.", "Thesis."

    monkeypatch.setattr(agent, "_report", report)
    notes = {}

    async def read(symbol):
        return notes.get(symbol)

    async def store(symbol, output):
        notes[symbol] = output

    first = await analysis.from_layer("TCS", read, store)
    assert first["sentiment_score"] == pytest.approx(0.465) and first["news_articles"][0]["impact_score"] == 8
    assert await analysis.from_layer("TCS", read, store) == first
    assert len(reports) == 1                       # second call reused the note
    assert await analysis.from_layer("ZOMATO", read, store) is None   # not followed: caller fetches
    del redis.data["ingest:heartbeat:news_process"]
    assert await analysis.from_layer("TCS", read, store) is None      # ingest down: caller fetches


async def _async(value):
    return value


async def test_deep_budget_stops_at_the_daily_cap(monkeypatch):
    monkeypatch.setattr(news.settings, "NEWS_LLM_CALLS_PER_DAY", 7)
    redis = FakeRedis()
    assert [await news._deep_budget(redis, 5) for _ in range(3)] == [5, 2, 0]
