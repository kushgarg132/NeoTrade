"""The backlog from a shell, for agents working on this repo (the routes need an
admin session). Same store and validation as /lab/backlog.

    docker exec neotrade-backend python -m backend.system.backlog_cli list [--all]
    docker exec neotrade-backend python -m backend.system.backlog_cli show <id>
    docker exec neotrade-backend python -m backend.system.backlog_cli add "Title" --area UI --status doing --why "..."
    docker exec neotrade-backend python -m backend.system.backlog_cli set <id> --status done --notes "..."
"""

import argparse
import asyncio
import json
from typing import get_args

from backend.system import backlog

OPEN = ("doing", "next", "idea")
FIELDS = ("area", "status", "why", "notes", "effort", "source")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backlog_cli")
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="open items, doing first")
    listing.add_argument("--all", action="store_true", help="include done and dropped")

    commands.add_parser("show", help="one item in full").add_argument("id")

    fields = argparse.ArgumentParser(add_help=False)
    fields.add_argument("--status", choices=get_args(backlog.Status))
    fields.add_argument("--why")
    fields.add_argument("--notes", help="replaces the notes: show them first to keep them")
    fields.add_argument("--effort", choices=("S", "M", "L"))
    fields.add_argument("--source")

    add = commands.add_parser("add", parents=[fields], help="new item")
    add.add_argument("title")
    add.add_argument("--area", required=True, choices=get_args(backlog.Area))

    change = commands.add_parser("set", parents=[fields], help="change an item")
    change.add_argument("id")
    change.add_argument("--title")
    change.add_argument("--area", choices=get_args(backlog.Area))
    return parser


def _given(args) -> dict:
    return {f: getattr(args, f) for f in FIELDS if getattr(args, f) is not None}


def _line(item: dict) -> str:
    return f"{item['id']}  {item['status']:<7}  {item['area']:<7}  {item.get('effort') or '-'}  {item['title']}"


async def run(db, argv: list[str]) -> str:
    args = _parser().parse_args(argv)
    if args.command == "add":
        return _line(await backlog.create(db, backlog.ItemIn(title=args.title, **_given(args))))
    if args.command == "set":
        changes = _given(args) | ({"title": args.title} if args.title else {})
        if not changes:
            raise SystemExit("Nothing to change")
        item = await backlog.update(db, args.id, backlog.ItemPatch(**changes))
    else:
        items = await backlog.list_items(db)
        if args.command == "list":
            return "\n".join(_line(i) for i in items if args.all or i["status"] in OPEN)
        item = next((i for i in items if i["id"] == args.id), None)
        if item:
            return json.dumps(item, indent=2, default=str)
    if not item:
        raise SystemExit(f"No such backlog item: {args.id}")
    return _line(item)


async def _main() -> None:
    import sys

    from backend.database import db

    await db.connect_to_database()
    print(await run(db.db, sys.argv[1:]))


if __name__ == "__main__":
    asyncio.run(_main())
