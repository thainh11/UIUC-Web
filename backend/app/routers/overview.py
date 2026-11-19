from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
import psycopg

from ..db import get_conn
from ..schemas import MonthCount, NameCount, Overview

router = APIRouter(prefix="/api")

LEVELS = {"domain": "t.domain", "field": "t.field", "subfield": "t.subfield", "topic": "t.name"}


@router.get("/overview", response_model=Overview)
def overview(conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    return conn.execute(
        """SELECT (SELECT count(*) FROM papers) AS papers,
                  (SELECT coalesce(sum(cited_by_count), 0) FROM papers) AS citations,
                  (SELECT avg(is_oa::int) FROM papers) AS open_access_share,
                  (SELECT min(publication_date) FROM papers) AS first_date,
                  (SELECT max(publication_date) FROM papers) AS last_date,
                  (SELECT count(DISTINCT primary_topic_id) FROM papers) AS topics,
                  (SELECT count(*) FROM faculty) AS faculty,
                  (SELECT count(DISTINCT faculty_id) FROM paper_authors) AS linked_faculty,
                  (SELECT count(DISTINCT author_id) FROM paper_authors WHERE is_uiuc) AS uiuc_authors"""
    ).fetchone()


@router.get("/stats/publications-by-month", response_model=list[MonthCount])
def publications_by_month(conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    return conn.execute(
        """SELECT to_char(date_trunc('month', publication_date), 'YYYY-MM') AS month, count(*) AS count,
                  count(*) FILTER (WHERE to_char(publication_date, 'MM-DD') = '01-01') AS year_only
           FROM papers GROUP BY 1 ORDER BY 1"""
    ).fetchall()


@router.get("/stats/topics", response_model=list[NameCount])
def topic_distribution(
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    level: Literal["domain", "field", "subfield", "topic"] = "field",
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
):
    """Papers per OpenAlex topic hierarchy level, by primary topic."""
    return conn.execute(
        f"""SELECT {LEVELS[level]} AS name, count(*) AS count
            FROM papers p JOIN topics t ON t.id = p.primary_topic_id
            GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %s""",
        [limit],
    ).fetchall()
