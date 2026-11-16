from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

class Base(DeclarativeBase): pass

def database(url):
    if url.startswith('sqlite:///') and ':memory:' not in url:
        Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True, **({'connect_args': {'check_same_thread':False}} if url.startswith('sqlite') else {}))
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def setup(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA busy_timeout=10000')
    return engine, sessionmaker(engine, expire_on_commit=False)

@contextmanager
def transaction(factory):
    with factory() as db:
        with db.begin(): yield db
