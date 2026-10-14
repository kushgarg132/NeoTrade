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


import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "real_gate: run risk/paper_gate.proven_strategies for real")


@pytest.fixture(autouse=True)
def _every_strategy_proven(request, monkeypatch):
    """Ideas reach the user's account only from strategies proven on the AI
    account (paper_gate.for_mine). Tests about anything else see every idea;
    tests of the gate itself are marked real_gate."""
    if request.node.get_closest_marker("real_gate"):
        return
    from backend.risk import paper_gate

    async def proven(db, user_id, names, account_size):
        return set(names)

    async def everything(db, user_id, proposals):
        return proposals

    monkeypatch.setattr(paper_gate, "proven_strategies", proven)
    monkeypatch.setattr(paper_gate, "for_mine", everything)
