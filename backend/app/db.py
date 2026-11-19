from collections.abc import Iterator
import os

from dotenv import load_dotenv
from fastapi import Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
import psycopg

load_dotenv()


def make_pool() -> ConnectionPool:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL missing (see .env.example)")
    return ConnectionPool(url, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=False)


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as conn:
        yield conn
