"""Bounded workers own their fetcher/browser; host leases coordinate requests."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event
from sqlalchemy import select
from .network import SafeFetcher
from .pipeline import process_one, discover
from .models import Source


def run_workers(factory, settings, workers=4, stop=None):
    if not 1 <= workers <= 8: raise ValueError('workers_must_be_1_to_8')
    stop = stop or Event()
    def loop(index):
        with SafeFetcher(settings, factory) as fetcher:
            while not stop.is_set():
                if not process_one(factory, settings, worker=str(index), fetcher=fetcher):
                    stop.wait(1)
    def schedule():
        while not stop.is_set():
            with factory() as db:
                ids=list(db.scalars(select(Source.id).where(Source.enabled)))
            for source_id in ids:discover(factory,source_id)
            stop.wait(60)
    with ThreadPoolExecutor(max_workers=workers+1) as pool:
        futures=[pool.submit(loop,i) for i in range(workers)]
        futures.append(pool.submit(schedule))
        try:
            for future in as_completed(futures):future.result()
        finally:stop.set()
