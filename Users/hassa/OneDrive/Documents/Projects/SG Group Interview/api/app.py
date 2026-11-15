"""Optional FastAPI surface: one POST /generate endpoint.

Run it with:  python cli.py serve   (or  uvicorn api.app:app --reload)
Interactive docs at http://127.0.0.1:8000/docs

The same EmailRequest/EmailResponse pydantic models power the CLI, the evaluator,
and this endpoint — one validated contract, three entry points.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from assistant.client import LLMClient, LLMError
from assistant.generator import generate
from assistant.schema import EmailRequest, EmailResponse

load_dotenv()

app = FastAPI(
    title="Email Generation Assistant",
    version="1.0.0",
    description="Generate professional emails from intent, key facts, and tone.",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/generate", response_model=EmailResponse)
def generate_email(
    request: EmailRequest,
    strategy: str = Query("advanced", pattern="^(advanced|baseline)$"),
) -> EmailResponse:
    """Generate an email. `strategy` selects the advanced or baseline prompt."""
    try:
        client = LLMClient.from_env("gen")
        temperature = float(os.getenv("GEN_TEMPERATURE", "0.3"))
        return generate(request, strategy, client, temperature=temperature)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
