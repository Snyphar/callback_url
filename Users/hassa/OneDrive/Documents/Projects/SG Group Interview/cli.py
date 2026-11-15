"""Command-line interface for the Email Generation Assistant.

Examples
--------
  # Generate a single email (uses GEN_PROVIDER from .env; needs an API key)
  python cli.py generate \
      --intent "Follow up after meeting" \
      --fact "Enjoyed the discussion on pricing" \
      --fact "Will send the contract on Monday" \
      --tone "warm and professional" --recipient "Priya" --sender "Daniel"

  # Run the full evaluation (advanced vs baseline) and write results + report
  python cli.py evaluate

  # Reproduce the committed evaluation offline from recorded outputs, no API key
  python cli.py evaluate --provider replay

  # Launch the FastAPI server
  python cli.py serve
"""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from assistant.client import LLMClient, LLMError
from assistant.generator import generate
from assistant.schema import EmailRequest

ROOT = os.path.dirname(os.path.abspath(__file__))


def _friendly_llm_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    lines = ["\nERROR: the LLM call failed (this is a provider/account issue, not a code bug).", f"  {msg}", ""]
    if any(k in low for k in ("429", "resource_exhausted", "quota", "rate limit", "rate-limit")):
        lines += [
            "-> Rate-limit / quota error from the provider. Options:",
            "   - Wait ~60s and retry (if it's a per-minute limit).",
            "   - Try a different model:  set GEN_MODEL / JUDGE_MODEL in .env (e.g. gemini-2.5-flash).",
            "   - Enable billing on your provider project (this whole workload costs ~1 cent).",
            "   - Switch provider in .env (GEN_PROVIDER=openai or anthropic) with the matching key.",
            "   - Reproduce the committed eval offline, no key:  python cli.py evaluate --provider replay",
        ]
    elif any(k in low for k in ("api key", "unauthor", "401", "403", "permission", "invalid")):
        lines += [
            "-> Looks like an authentication problem. Check that:",
            "   - The key in .env matches GEN_PROVIDER (OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY).",
            "   - The key is active and has access to the configured model.",
        ]
    else:
        lines += ["-> Run `python cli.py evaluate --provider replay` to reproduce the eval offline."]
    return "\n".join(lines)


def _cmd_generate(args: argparse.Namespace) -> int:
    load_dotenv(os.path.join(ROOT, ".env"))
    if args.provider:
        os.environ["GEN_PROVIDER"] = args.provider
    request = EmailRequest(
        intent=args.intent,
        key_facts=args.fact,
        tone=args.tone,
        recipient=args.recipient,
        sender=args.sender,
    )
    try:
        client = LLMClient.from_env("gen")
        temperature = float(os.getenv("GEN_TEMPERATURE", "0.3"))
        email = generate(request, args.strategy, client, temperature=temperature)
    except LLMError as exc:
        print(_friendly_llm_error(exc), file=sys.stderr)
        return 1

    print(f"\n[{client.label()} | strategy={args.strategy}]")
    print("-" * 60)
    print(f"SUBJECT: {email.subject}\n")
    print(email.body)
    print("-" * 60)
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    if args.provider:
        os.environ["GEN_PROVIDER"] = args.provider
        os.environ["JUDGE_PROVIDER"] = args.provider
    from evaluation.runner import run_evaluation

    try:
        run_evaluation(strategies=args.strategies, limit=args.limit)
    except LLMError as exc:
        print(_friendly_llm_error(exc), file=sys.stderr)
        return 1
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Email Generation Assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Generate a single email")
    g.add_argument("--intent", required=True)
    g.add_argument("--fact", action="append", required=True, help="Repeatable key fact")
    g.add_argument("--tone", required=True)
    g.add_argument("--recipient", default=None)
    g.add_argument("--sender", default=None)
    g.add_argument("--strategy", default="advanced", choices=["advanced", "baseline"])
    g.add_argument("--provider", default=None, help="Override GEN_PROVIDER for this call")
    g.set_defaults(func=_cmd_generate)

    e = sub.add_parser("evaluate", help="Run the full evaluation + write report")
    e.add_argument(
        "--strategies", nargs="+", default=["advanced", "baseline"],
        choices=["advanced", "baseline"],
    )
    e.add_argument("--limit", type=int, default=None, help="Only run the first N scenarios")
    e.add_argument("--provider", default=None, help="Override gen+judge provider (e.g. replay)")
    e.set_defaults(func=_cmd_evaluate)

    s = sub.add_parser("serve", help="Launch the FastAPI /generate endpoint")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(func=_cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
