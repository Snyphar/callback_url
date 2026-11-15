"""Pydantic models for the assistant's input and output.

Keeping the contract explicit (and validated) is what lets the same `EmailRequest`
flow through the CLI, the FastAPI endpoint, and the evaluation runner unchanged.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EmailRequest(BaseModel):
    """The three required inputs (intent, key facts, tone) plus optional context."""

    intent: str = Field(..., min_length=3, description="Core purpose of the email.")
    key_facts: list[str] = Field(
        ..., min_length=1, description="Facts that must be seamlessly included."
    )
    tone: str = Field(..., min_length=2, description="Desired style, e.g. formal, empathetic.")
    recipient: Optional[str] = Field(
        None, description="Who the email is addressed to (used for the greeting)."
    )
    sender: Optional[str] = Field(
        None, description="Sender display name used in the signature. Defaults to a placeholder."
    )

    @field_validator("key_facts")
    @classmethod
    def _strip_and_require_facts(cls, value: list[str]) -> list[str]:
        cleaned = [f.strip() for f in value if f and f.strip()]
        if not cleaned:
            raise ValueError("key_facts must contain at least one non-empty fact.")
        return cleaned


class EmailResponse(BaseModel):
    """The structured output. `raw` keeps the unparsed model text for debugging."""

    subject: str
    body: str
    strategy: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    raw: Optional[str] = Field(None, description="Unparsed model output, for inspection.")
