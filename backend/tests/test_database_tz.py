"""The production Mongo client hands back UTC-aware datetimes, so no route can
send a bare time the browser reads as IST (5h30m early)."""

from datetime import timezone

from backend.database import mongo_client


def test_production_client_is_tz_aware():
    client = mongo_client("mongodb://localhost:27017")
    assert client.codec_options.tz_aware is True
    assert client.codec_options.tzinfo == timezone.utc
