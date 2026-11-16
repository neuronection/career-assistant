"""CV export request + parse-view schemas (plan 212 S1.2)."""

from typing import Literal

from pydantic import BaseModel, Field


class CvExportRequest(BaseModel):
    format: Literal["pdf", "docx", "md", "json", "ats_text"]


class CvParseViewPage(BaseModel):
    """One printed page's extracted text — exactly what this app's own
    extractor sees, verbatim."""

    index: int = Field(ge=0)
    text: str = Field(max_length=20_000)
    line_count: int = Field(ge=0)


class CvParseViewFinding(BaseModel):
    """One deterministic finding — never a score, never a vendor name."""

    id: str = Field(min_length=1, max_length=40)
    level: Literal["info", "warn", "fail"]
    message: str = Field(min_length=1, max_length=500)


class CvParseViewOut(BaseModel):
    """What our extractor sees in the exported PDF: per-page text,
    findings, the page count and whether a text layer exists at all.
    `engine` names our own pipeline ("pdf" = printed through the server
    print engine); this is explicitly NOT a vendor simulation."""

    pages: list[CvParseViewPage] = Field(default_factory=list, max_length=20)
    findings: list[CvParseViewFinding] = Field(default_factory=list, max_length=10)
    page_count: int = Field(ge=0)
    text_layer: bool
    engine: Literal["pdf"] = "pdf"
