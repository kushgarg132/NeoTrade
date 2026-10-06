"""One-time seed of the backlog from every open item in the roadmap, its
deferred lists, the 2026-10-05 audit and the 2026-10-06 session. Upserts by
title, so running it again adds nothing.

    docker exec neotrade-backend python -m backend.system.seed_backlog
"""

import asyncio
from datetime import datetime, timezone

from backend.system.backlog import COLLECTION


def _item(title, area, why, source, status="idea", effort=None):
    return {"title": title, "area": area, "status": status, "why": why, "source": source, "effort": effort}


SEED = [
    # Product direction
    _item("Free beta: recruit 20-50 traders", "Product",
          "Learn whether traders come back weekly, and open the journal after a losing day, before building billing.",
          "ROADMAP Phase 12", "next", "L"),
    _item("Publish the Google OAuth consent screen", "Product",
          "In Testing mode only listed test users can sign in; strangers in the beta would be refused.",
          "ROADMAP Phase 12", "next", "S"),
    _item("Add neotrade-trading.vercel.app to Google OAuth JavaScript origins", "Ops",
          "Google sign-in on the new frontend URL depends on it; only the old alias is authorised.",
          "ROADMAP Phase 0", "next", "S"),
    _item("Real domain replacing nip.io, with privacy, terms and refund pages", "Product",
          "Needed for Razorpay KYC and for trust.", "ROADMAP Phase 13", effort="M"),
    _item("Razorpay subscriptions (Free / Pro)", "Product",
          "Free: 1 broker, 30 days of journal. Pro: unlimited history, insights, guardrails, multiple brokers. Only after the beta shows weekly return.",
          "ROADMAP Phase 13", effort="L"),
    _item("Check Kite Connect fees and multi-user app rules", "Product",
          "Before launch: Kite Connect may charge per app and restrict third-party multi-user use.",
          "ROADMAP Phase 13", effort="S"),
    _item("Insights page: plain-language findings about my own habits", "Journal",
          "PRODUCT.md lists Insights as planned, e.g. 'trades after 2 losses in a row: 31% win rate'.",
          "PRODUCT.md surfaces", effort="M"),
    _item("Import Upstox and Angel One trade exports", "Journal",
          "Only Zerodha Console CSV is importable; Upstox has an API import, Angel One has nothing.",
          "ROADMAP Phase 9 known limits", effort="M"),
    _item("Page GET /journal by date", "Journal",
          "It loads a user's whole history every call; fine now, slow at tens of thousands of fills.",
          "ROADMAP Phase 9 known limits", effort="S"),
    _item("Net P&L in the journal from contract-note charges", "Journal",
          "Broker trade books carry no brokerage/STT, so journal P&L is gross; the mirror only estimates charges.",
          "ROADMAP Phase 9 known limits", effort="M"),
    # Trading and engine
    _item("Factor portfolio live (Phase E)", "Trading",
          "Only after report --save passes, 3+ months of paper beat Nifty, and an opt-in start small. Needs LIQUIDBEES orders for the risk-off sleeve.",
          "ROADMAP 2026-10-04 factor portfolio", effort="L"),
    _item("Intraday re-tune from a year of Kite history", "Trading",
          "yfinance's ~60 days of 5-minute bars leave too short a window for the monthly re-tune to pass.",
          "ROADMAP 2026-10-04 learning loop", effort="M"),
    _item("Faster backtest runner (vectorised indicators)", "Trading",
          "~125 bars/s, ~30 min per intraday strategy: strategies recompute indicators every bar.",
          "ROADMAP 2026-10-04 learning loop", effort="M"),
    _item("Covered call strategy", "Trading", "The other half of the options income pair next to the cash-secured put.",
          "ROADMAP Phase 5b+", effort="M"),
    _item("Upstox / Angel One NFO instrument mapping", "Data",
          "Option contracts come from Kite's dump only; Upstox spells option symbols differently.",
          "ROADMAP Phase 5b+", effort="M"),
    _item("Live broker margin API for options sizing", "Trading",
          "estimate_margin is a model (ponytail comment in backend/options/pricing.py).",
          "ROADMAP Phase 5b+", effort="M"),
    _item("Expiry-day findings for options trades", "Journal",
          "Needs a reliable expiry per traded contract.", "ROADMAP 2026-09-27 options in the journal", effort="S"),
    _item("Fix owner_by_symbol last-writer-wins attribution", "Trading",
          "Two strategies on one symbol can mislabel which strategy an intent came from (backend/engine/runner.py).",
          "ROADMAP Phase 6 deferred", effort="S"),
    _item("Cache the quality universe once a day", "Data",
          "scan_universe rebuilds it per user per scan with fresh yfinance calls.", "ROADMAP Phase 6 deferred", effort="S"),
    _item("Remove orphaned TradeSignal / SignalType models", "System",
          "Dead code in backend/components/shared/models.py.", "ROADMAP Phase 6 deferred", effort="S"),
    _item("Reconcile live orders per broker role (audit M3)", "Trading",
          "Live orders from approve-live, chat and autopilot are never re-polled; the engine poller reads every row vs the AI adapter.",
          "audit 2026-10-05", "next", "M"),
    _item("Run square-off in preview on a real account", "Trading",
          "The one path that places real orders without a per-trade tap has never run live; check its reported orders first.",
          "ROADMAP Phase 11", "next", "S"),
    # Portfolio
    _item("Portfolio: P/E against the stock's own history, debt trend", "Data",
          "Health uses a P/E level and a debt level only.", "ROADMAP 2026-09-27 portfolio 3-5", effort="M"),
    _item("Portfolio: ETF/MF overlap and expense ratios", "Data",
          "Needs a holdings/expense data source the app does not have; ETFs are recognised by name only.",
          "ROADMAP 2026-09-27 portfolio 1-2", effort="L"),
    _item("Open verdicts to all users after SEBI RA registration", "Product",
          "Verdicts and the AI action plan are admin-only by design until then.", "PRODUCT.md Holdings", effort="L"),
    # AI and news
    _item("News ingest: stop tagging market-wide stories to single symbols", "News",
          "A US software story got tagged ADANIPOWER, so 'My names' shows general news.",
          "session 2026-10-06", "next", "M"),
    _item("Check the AI plan prose has no field names", "AI",
          "Today's plan still read add_symbols / skip_day; 8faab51 fixed the prompt, the next plan proves it.",
          "session 2026-10-06", "next", "S"),
    _item("Warm the gateway usage reading at startup", "AI",
          "The first Settings/AI visit after a deploy waits ~4 s per worker on OmniRoute's live quota poll.",
          "session 2026-10-06", effort="S"),
    _item("Per-task AI call counters", "AI",
          "Only news scoring and plans have daily budgets; chat and research calls are not counted.",
          "handbook spec 2026-10-06", effort="S"),
    _item("Finnhub API key for news", "News", "Source configured but no key set.", "audit 2026-10-05 user_todo", effort="S"),
    # UI
    _item("Fetch preferences once per page", "UI", "Prefs are fetched about six times per page load.",
          "audit 2026-10-05 skipped", effort="S"),
    # Ops and platform
    _item("Rotate the nginx access log", "Ops", "41 old tokens sit in /var/log/nginx/access.log from before redaction.",
          "audit 2026-10-05 user_todo", "next", "S"),
    _item("Smoke-test two workers end to end on the VM", "Ops",
          "Multi-worker behaviour is unit-tested on mocked Redis only.", "ROADMAP Phase 7 deferred", effort="S"),
    _item("Shared Telegram notifier across projects", "Ops", "Item 4 of the shared-platform extraction.",
          "shared-platform plan", effort="M"),
    _item("Shared shadcn component registry", "UI", "Item 5 of the shared-platform extraction.",
          "shared-platform plan", effort="M"),
    _item("Project template repo", "Ops", "Item 6 of the shared-platform extraction.", "shared-platform plan", effort="M"),
    _item("Route NeoTrade AI through a shared OmniRoute policy", "AI",
          "Item 3 of the shared-platform extraction; needs a decision on bring-your-own-key vs shared gateway.",
          "shared-platform plan", effort="M"),
]


async def seed(db) -> int:
    now = datetime.now(timezone.utc)
    counters: dict[str, int] = {}
    inserted = 0
    for item in SEED:
        rank = counters.get(item["status"], 0)
        counters[item["status"]] = rank + 1
        result = await db[COLLECTION].update_one(
            {"title": item["title"]},
            {"$setOnInsert": {**item, "notes": "", "rank": rank, "created_at": now, "updated_at": now, "done_at": None}},
            upsert=True,
        )
        inserted += 1 if result.upserted_id is not None else 0
    return inserted


async def _main() -> None:
    from backend.database import db

    await db.connect_to_database()
    print(f"backlog: {await seed(db.db)} item(s) added of {len(SEED)}")


if __name__ == "__main__":
    asyncio.run(_main())
