from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
import psycopg

from ..db import get_conn
from ..schemas import FacultyDetail, FacultyPage
from ..services.papers import list_papers

router = APIRouter(prefix="/api/faculty")

FACULTY_COLUMNS = """
  f.id, f.name, f.email, f.photo_url, f.position,
  (SELECT count(DISTINCT paper_id) FROM paper_authors WHERE faculty_id = f.id) AS paper_count,
  (SELECT coalesce(json_agg(x.field), '[]'::json) FROM (
     SELECT t.field FROM paper_authors pa
       JOIN papers p ON p.id = pa.paper_id JOIN topics t ON t.id = p.primary_topic_id
      WHERE pa.faculty_id = f.id AND t.field IS NOT NULL
      GROUP BY t.field ORDER BY count(*) DESC, t.field LIMIT 3) x) AS top_fields
"""


def like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("", response_model=FacultyPage)
def faculty(
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    query: Annotated[str | None, Query(max_length=300, description="Substring of name or of a research keyword")] = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
):
    where, params = "TRUE", []
    if query:
        where = """(f.name ILIKE %s OR EXISTS (
                      SELECT 1 FROM faculty_keywords fk JOIN keywords k ON k.id = fk.keyword_id
                       WHERE fk.faculty_id = f.id AND k.text ILIKE %s))"""
        params = [like(query)] * 2
    total = conn.execute(f"SELECT count(*) AS n FROM faculty f WHERE {where}", params).fetchone()["n"]
    items = conn.execute(
        f"""SELECT * FROM (SELECT {FACULTY_COLUMNS} FROM faculty f WHERE {where}) s
            ORDER BY paper_count DESC, name, id LIMIT %s OFFSET %s""",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{faculty_id}", response_model=FacultyDetail)
def faculty_detail(faculty_id: int, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    row = conn.execute(f"SELECT {FACULTY_COLUMNS} FROM faculty f WHERE f.id = %s", [faculty_id]).fetchone()
    if row is None:
        raise HTTPException(404, "faculty not found")
    row["keywords"] = [
        r["text"]
        for r in conn.execute(
            """SELECT k.text FROM faculty_keywords fk JOIN keywords k ON k.id = fk.keyword_id
               WHERE fk.faculty_id = %s ORDER BY k.text""",
            [faculty_id],
        )
    ]
    row["papers"], _ = list_papers(conn, faculty_id=faculty_id, sort="date", page=1, page_size=100)
    return row
