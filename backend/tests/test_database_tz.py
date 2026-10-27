"""The production Mongo client hands back UTC-aware datetimes, so no route can
send a bare time the browser reads as IST (5h30m early)."""

from datetime import timezone

from backend.database import mongo_client


def test_production_client_is_tz_aware():
    client = mongo_client("mongodb://localhost:27017")
    assert client.codec_options.tz_aware is True
    assert client.codec_options.tzinfo == timezone.utc


async def test_routed_database_sends_market_data_collections_to_the_local_mongo():
    from mongomock_motor import AsyncMongoMockClient
    from backend.database import RoutedDatabase

    main, local = AsyncMongoMockClient()["d"], AsyncMongoMockClient()["d"]
    db = RoutedDatabase(main, local)
    await db["daily_bars"].insert_one({"s": 1})
    await db.news_history.insert_one({"s": 2})
    await db["users"].insert_one({"s": 3})
    await db.watchlist.insert_one({"s": 4})
    assert sorted(await local.list_collection_names()) == ["daily_bars", "news_history"]
    assert sorted(await main.list_collection_names()) == ["users", "watchlist"]
    assert sorted(await db.list_collection_names()) == ["users", "watchlist"]  # non-collection calls: Atlas
