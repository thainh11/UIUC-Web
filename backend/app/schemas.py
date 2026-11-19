from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Overview(BaseModel):
    papers: int
    citations: int
    open_access_share: float
    first_date: date
    last_date: date
    topics: int
    faculty: int
    linked_faculty: int
    uiuc_authors: int  # distinct OpenAlex author ids with a UIUC-affiliated authorship (a person may have several)


class MonthCount(BaseModel):
    month: str  # YYYY-MM; the first and last months are partial (rolling 24-month window)
    count: int
    # Papers dated 1 January. A year-only publication date shows up that way (about 650 per January 1st, while any
    # other day has a median of 24), so plotting them under January makes every January look like a spike.
    year_only: int


class NameCount(BaseModel):
    name: str
    count: int


class FacultyRef(BaseModel):
    id: int
    name: str


class PaperSummary(BaseModel):
    id: str
    doi: str | None
    title: str
    publication_date: date
    cited_by_count: int
    is_oa: bool
    venue: str | None
    type: str
    topic: str | None
    field: str | None
    domain: str | None
    authors: list[str]  # first authors only
    author_count: int
    faculty: list[FacultyRef]  # faculty linked to this paper
    relevance: float | None = None  # only with a text query


class PaperPage(BaseModel):
    items: list[PaperSummary]
    total: int
    page: int
    page_size: int


class PaperAuthor(BaseModel):
    name: str
    position: int
    is_uiuc: bool
    faculty_id: int | None


class PaperTopic(BaseModel):
    name: str
    field: str | None
    score: float


class PaperDetail(PaperSummary):
    abstract: str
    oa_status: str | None
    keywords: list[str]
    topics: list[PaperTopic]
    all_authors: list[PaperAuthor]


class FacultySummary(BaseModel):
    id: int
    name: str
    email: str
    photo_url: str | None
    position: str | None
    paper_count: int
    top_fields: list[str]


class FacultyPage(BaseModel):
    items: list[FacultySummary]
    total: int
    page: int
    page_size: int


class FacultyDetail(FacultySummary):
    keywords: list[str]
    papers: list[PaperSummary]


class ChatTurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class ChatContext(BaseModel):
    """The record the page is showing. Only a name: the server looks the record up."""

    kind: Literal["faculty"]
    id: int


class ChatKnown(BaseModel):
    """A record cited earlier in the conversation (paper: OpenAlex id, faculty: numeric id)."""

    kind: Literal["paper", "faculty"]
    id: str = Field(min_length=1, max_length=40)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurnIn] = Field(default_factory=list, max_length=20)
    context: ChatContext | None = None
    known: list[ChatKnown] = Field(default_factory=list, max_length=30)
