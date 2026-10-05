"""Test-wide setup.

Production's Mongo client is timezone-aware (backend/database.py), so every
mongomock client in the suite is too: a datetime read back from a test
database carries UTC exactly as it does in production.
"""

import mongomock_motor

_init = mongomock_motor.AsyncMongoMockClient.__init__


def _tz_aware_init(self, *args, **kwargs):
    kwargs.setdefault("tz_aware", True)
    _init(self, *args, **kwargs)


mongomock_motor.AsyncMongoMockClient.__init__ = _tz_aware_init
