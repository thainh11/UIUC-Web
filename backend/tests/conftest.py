from collections.abc import Iterator
import os

from dotenv import load_dotenv
from psycopg.rows import dict_row
import psycopg
import pytest

load_dotenv()


@pytest.fixture(scope="session")
def db() -> Iterator[psycopg.Connection]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL missing (see .env.example)")
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as conn:
        yield conn


@pytest.fixture(scope="module")
def pool():
    from backend.app.db import make_pool

    pool = make_pool()
    pool.open(wait=True)
    yield pool
    pool.close()


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client
