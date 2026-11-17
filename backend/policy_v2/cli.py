"""Operational commands for the opt-in V2 service."""
import argparse
import json
import time

from sqlalchemy import select

from .app import Base, SessionLocal, engine, settings
from .models import Source
from .pipeline import discover, process_one
from .network import SafeFetcher
from .migrate import migrate_documents


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sources")
    discover_cmd = commands.add_parser("discover"); discover_cmd.add_argument("source_id", nargs="?")
    commands.add_parser("worker")
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
        with SafeFetcher(settings) as fetcher:
            while True:
                if not process_one(SessionLocal, settings, fetcher=fetcher): time.sleep(1)
    elif args.command == "migrate":
        print(json.dumps(migrate_documents(args.legacy_sqlite, SessionLocal), ensure_ascii=False))


if __name__ == "__main__": main()
