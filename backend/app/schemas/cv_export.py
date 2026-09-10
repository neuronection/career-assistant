"""CV export request schema."""

from typing import Literal

from pydantic import BaseModel


class CvExportRequest(BaseModel):
    format: Literal["pdf", "docx", "md", "json", "ats_text"]
