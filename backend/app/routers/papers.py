from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
import psycopg

from ..db import get_conn
from ..schemas import PaperDetail, PaperPage
from ..services.papers import FROM, SUMMARY_COLUMNS, list_papers

router = APIRouter(prefix="/api/papers")


@router.get("", response_model=PaperPage)
def papers(
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    query: Annotated[str | None, Query(max_length=300, description="Full-text search over title + abstract")] = None,
    topic: Annotated[str | None, Query(description="OpenAlex topic id, e.g. T11265")] = None,
    subfield: str | None = None,
    field: str | None = None,
    domain: str | None = None,
    sort: Literal["date", "citations", "relevance"] = "date",
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
):
    items, total = list_papers(
        conn, query=query, topic=topic, subfield=subfield, field=field, domain=domain,
        sort=sort, page=page, page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{paper_id}", response_model=PaperDetail)
def paper(paper_id: str, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    row = conn.execute(
        f"""SELECT {SUMMARY_COLUMNS}, p.abstract, p.oa_status, p.keywords, NULL::real AS relevance
            FROM {FROM} WHERE p.id = %s""",
        [paper_id],
    ).fetchone()
    if row is None:
        raise HTTPException(404, "paper not found")
    row["topics"] = conn.execute(
        """SELECT t.name, t.field, pt.score FROM paper_topics pt JOIN topics t ON t.id = pt.topic_id
           WHERE pt.paper_id = %s ORDER BY pt.score DESC""",
        [paper_id],
    ).fetchall()
    row["all_authors"] = conn.execute(
        "SELECT name, position, is_uiuc, faculty_id FROM paper_authors WHERE paper_id = %s ORDER BY position",
        [paper_id],
    ).fetchall()
    return row
