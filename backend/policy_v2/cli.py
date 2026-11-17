"""Operational commands for the opt-in V2 service."""
import argparse
import json

from sqlalchemy import select

from .app import Base, SessionLocal, engine, settings
from .models import Source
from .pipeline import discover
from .migrate import migrate_documents


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sources")
    discover_cmd = commands.add_parser("discover"); discover_cmd.add_argument("source_id", nargs="?")
    worker_cmd = commands.add_parser("worker"); worker_cmd.add_argument("--workers", type=int, default=4)
    commands.add_parser("inventory")
    migrate_cmd = commands.add_parser("migrate"); migrate_cmd.add_argument("legacy_sqlite")
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    if args.command == "sources":
        with SessionLocal() as db:
            print(json.dumps([{"id": s.id, "enabled": s.enabled, "url": s.url} for s in db.scalars(select(Source))], ensure_ascii=False, indent=2))
    elif args.command == "discover":
        with SessionLocal() as db:
            ids = [args.source_id] if args.source_id else list(db.scalars(select(Source.id).where(Source.enabled)))
        print("scheduled list pages:", sum(discover(SessionLocal, sid) for sid in ids))
    elif args.command == "worker":
        from .worker import run_workers
        run_workers(SessionLocal, settings, args.workers)
    elif args.command == "inventory":
        from .sources import inventory, source_definitions
        print(json.dumps({"provinces": inventory(), "sources": source_definitions()}, ensure_ascii=False, indent=2))
    elif args.command == "migrate":
        print(json.dumps(migrate_documents(args.legacy_sqlite, SessionLocal), ensure_ascii=False))


if __name__ == "__main__": main()
