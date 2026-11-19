"""The three tools the chat model can call, and the citation bookkeeping around them.

Every paper or faculty member shown to the model gets a short reference (P1, F2, ...). The model cites with
those references; the server maps them back to real records, so a citation can only point at something that
was retrieved.
"""

from dataclasses import dataclass, field
import json

from psycopg_pool import ConnectionPool

from ..app.routers.faculty import FACULTY_COLUMNS
from ..app.services.papers import list_papers
from .faculty import find_faculty_by_name, search_faculty
from .search import search_papers
from .trace import Trace, active, note

MAX_LIMIT = 10
ABSTRACT_CHARS = 450

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_papers",
            "description": (
                "Search UIUC research papers from the last two years by topic. Returns the closest matches, which are "
                "not guaranteed to be relevant: read the titles and abstracts and ignore poor matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Topic phrase in English, e.g. 'artificial intelligence in war and armed conflict'. "
                        "No question words, no 'UIUC', no 'recent'.",
                    },
                    "sort_by_date": {
                        "type": "boolean",
                        "description": "True for 'most recent', 'latest', 'newest': keeps the on-topic papers, newest first.",
                    },
                    "year_from": {"type": "integer", "description": "Only papers published in or after this year."},
                    "limit": {"type": "integer", "description": f"1-{MAX_LIMIT}, default 6."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_faculty",
            "description": (
                "Find UIUC faculty members. By research topic: ranks people by the papers they wrote on the topic and by "
                "their research keywords. By name: looks the person up (needed to get a faculty_id)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic phrase, e.g. 'computer vision in healthcare'."},
                    "concepts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "When the topic combines several ideas, each one separately: ['computer vision', 'healthcare'].",
                    },
                    "name": {"type": "string", "description": "Part of a person's name. Use instead of topic."},
                    "limit": {"type": "integer", "description": f"1-{MAX_LIMIT}, default 8."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_faculty_papers",
            "description": "List the papers of one faculty member (newest first). Get faculty_id from search_faculty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "faculty_id": {"type": "integer"},
                    "limit": {"type": "integer", "description": f"1-{MAX_LIMIT}, default 8."},
                },
                "required": ["faculty_id"],
            },
        },
    },
]


@dataclass
class Citations:
    """References handed to the model during one chat turn."""

    sources: dict[str, dict] = field(default_factory=dict)
    _refs: dict[tuple[str, str | int], str] = field(default_factory=dict)

    def ref(self, kind: str, key: str | int, source: dict) -> str:
        known = self._refs.get((kind, key))
        if known:
            return known
        ref = f"{'P' if kind == 'paper' else 'F'}{sum(1 for k, _ in self._refs if k == kind) + 1}"
        self._refs[(kind, key)] = ref
        self.sources[ref] = {"ref": ref, "kind": kind, **source}
        return ref

    def paper(self, paper: dict) -> str:
        return self.ref(
            "paper",
            paper["id"],
            {"label": paper["title"], "date": str(paper["publication_date"]), "doi": paper.get("doi"), "paperId": paper["id"]},
        )

    def faculty(self, person: dict) -> str:
        return self.ref("faculty", person["id"], {"label": person["name"], "facultyId": person["id"]})


def _paper_view(paper: dict, citations: Citations) -> dict:
    abstract = paper.get("abstract") or ""
    if len(abstract) > ABSTRACT_CHARS:
        abstract = abstract[:ABSTRACT_CHARS].rsplit(" ", 1)[0] + "…"
    return {
        "ref": citations.paper(paper),
        "title": paper["title"],
        "date": str(paper["publication_date"]),
        "authors": paper["authors"],
        "uiuc_faculty": [f["name"] for f in paper["faculty"]],
        "topic": paper["topic"],
        "cited_by": paper["cited_by_count"],
        "abstract": abstract,
    }


def _limit(arguments: dict, default: int) -> int:
    value = arguments.get("limit", default)
    return max(1, min(int(value), MAX_LIMIT)) if isinstance(value, int | float) else default


def _search_papers(conn, arguments: dict, citations: Citations) -> dict:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    year = arguments.get("year_from")
    papers = search_papers(
        conn,
        query,
        sort_by_date=bool(arguments.get("sort_by_date")),
        year_from=int(year) if isinstance(year, int | float) else None,
        limit=_limit(arguments, 6),
    )
    if not papers:
        return {"results": [], "note": f"No UIUC paper in the data is related to '{query}'."}
    return {"results": [_paper_view(paper, citations) for paper in papers]}


def _faculty_view(person: dict, citations: Citations) -> dict:
    view = {
        "ref": citations.faculty(person),
        "faculty_id": person["id"],
        "name": person["name"],
        "position": person["position"],
        "email": person["email"],
        "papers_in_data": person["paper_count"],
        "main_fields": person["top_fields"],
    }
    if "evidence" in person:
        view["evidence"] = person["evidence"]
        view["matching_papers"] = person["matching_papers"]
        view["example_papers"] = [
            {"ref": citations.paper(p), "title": p["title"], "date": str(p["publication_date"])} for p in person["papers"]
        ]
        view["matching_keywords"] = [f"{k['keyword']} (for '{k['concept']}')" for k in person["keywords"]]
    return view


def _search_faculty(conn, arguments: dict, citations: Citations) -> dict:
    name = str(arguments.get("name") or "").strip()
    topic = str(arguments.get("topic") or "").strip()
    limit = _limit(arguments, 8)
    if name:
        people = find_faculty_by_name(conn, name, limit)
        if not people:
            return {"results": [], "note": f"No faculty member's name contains '{name}'."}
    elif topic:
        concepts = arguments.get("concepts")
        people = search_faculty(conn, topic, [str(c) for c in concepts] if isinstance(concepts, list) else None, limit=limit)
        if not people:
            return {"results": [], "note": f"No faculty member is related to '{topic}'."}
    else:
        return {"error": "give topic or name"}
    return {"results": [_faculty_view(person, citations) for person in people]}


def _get_faculty_papers(conn, arguments: dict, citations: Citations) -> dict:
    faculty_id = arguments.get("faculty_id")
    if not isinstance(faculty_id, int):
        return {"error": "faculty_id must be an integer"}
    person = conn.execute("SELECT id, name FROM faculty WHERE id = %s", [faculty_id]).fetchone()
    if person is None:
        return {"error": f"no faculty member with id {faculty_id}"}
    papers, total = list_papers(conn, faculty_id=faculty_id, sort="date", page=1, page_size=_limit(arguments, 8))
    return {
        "faculty": {"ref": citations.faculty(person), "name": person["name"]},
        "total_papers": total,
        "results": [_paper_view(paper, citations) for paper in papers],
    }


HANDLERS = {"search_papers": _search_papers, "search_faculty": _search_faculty, "get_faculty_papers": _get_faculty_papers}


def preload(pool: ConnectionPool, citations: Citations, context: dict | None, known: list[dict]) -> str:
    """Register the records the page or the conversation already points at; return their description for the prompt.

    `context` is the person whose profile the user has open; `known` are records cited earlier in the conversation.
    Ids that do not exist are dropped: the client only names records, the text comes from the database.
    """
    focus = ""
    lines: dict[str, str] = {}  # ref -> line; a record named twice is listed once
    with pool.connection() as conn:
        if context and context.get("kind") == "faculty":
            person = conn.execute(f"SELECT {FACULTY_COLUMNS} FROM faculty f WHERE f.id = %s", [context["id"]]).fetchone()
            if person:
                ref = citations.faculty(person)
                fields = ", ".join(person["top_fields"]) or "unknown"
                focus = (
                    f"Page context: the user has the profile of [{ref}] open: faculty_id={person['id']}, {person['name']}, "
                    f"{person['position'] or 'faculty member'}, {person['paper_count']} papers in the data, main fields: {fields}. "
                    "'He', 'she', 'they' and 'this person' mean this person unless the question names someone else. "
                    "This is identity only: for their papers call get_faculty_papers with this faculty_id."
                )
        faculty_ids = [int(k["id"]) for k in known if k["kind"] == "faculty" and str(k["id"]).isdigit()]
        paper_ids = [str(k["id"]) for k in known if k["kind"] == "paper"]
        people = {row["id"]: row for row in conn.execute("SELECT id, name FROM faculty WHERE id = ANY(%s)", [faculty_ids])}
        papers = {
            row["id"]: row
            for row in conn.execute("SELECT id, title, publication_date, doi FROM papers WHERE id = ANY(%s)", [paper_ids])
        }
    for item in known:
        if item["kind"] == "faculty" and str(item["id"]).isdigit() and int(item["id"]) in people:
            person = people[int(item["id"])]
            lines.setdefault(citations.faculty(person), f"faculty_id={person['id']} {person['name']}")
        elif item["kind"] == "paper" and str(item["id"]) in papers:
            paper = papers[str(item["id"])]
            lines.setdefault(citations.paper(paper), f"\"{paper['title']}\" ({paper['publication_date']})")
    earlier = ""
    if lines:
        earlier = (
            "Records already shown earlier in this conversation (cite them with their ref; for a person, pass the "
            "faculty_id to get_faculty_papers instead of searching by name again):\n"
            + "\n".join(f"- [{ref}] {line}" for ref, line in lines.items())
        )
    return "\n\n".join(part for part in (focus, earlier) if part)


def run_tool(pool: ConnectionPool, name: str, raw_arguments: str, citations: Citations, trace: Trace | None = None) -> str:
    """Execute one tool call and return the JSON the model reads. Bad input becomes an error the model can fix."""
    handler = HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "arguments are not valid JSON"})
    if not isinstance(arguments, dict):
        return json.dumps({"error": "arguments must be an object"})
    with active(trace), pool.connection() as conn:
        result = handler(conn, arguments, citations)
        note("tool.result", results=len(result.get("results") or ()), error=result.get("error"))
    return json.dumps(result, ensure_ascii=False, default=str)
