#!/usr/bin/env python
"""Generate clean English text for imported Eusebius passages."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import psycopg
from openai import OpenAI


MODE_DEFAULTS = {
    "cleanup": {
        "model": "gpt-5.6-luna",
        "prompt_version": "english-cleanup-v1",
        "daily_token_budget": 500_000,
    },
    "translate": {
        "model": "gpt-5.5",
        "prompt_version": "greek-translation-v1",
        "daily_token_budget": 10_000,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("EUSEBIUS_DATABASE_URL", "postgresql:///eusebius"),
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(MODE_DEFAULTS),
        default=os.environ.get("EUSEBIUS_TRANSLATION_MODE", "cleanup"),
        help="cleanup fixes rough English; translate creates a new Greek translation",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("EUSEBIUS_TRANSLATION_MODEL"),
        help="OpenAI model to use; defaults depend on --mode",
    )
    parser.add_argument(
        "--prompt-version",
        default=os.environ.get("EUSEBIUS_TRANSLATION_PROMPT_VERSION"),
        help="Prompt version stored with translation runs; defaults depend on --mode",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("EUSEBIUS_TRANSLATION_LIMIT", "5")),
        help="Maximum passages to translate in this run",
    )
    parser.add_argument(
        "--openai-api-key-file",
        default=os.environ.get("OPENAI_API_KEY_FILE", "~/.openai.eusebius.key"),
        help="Optional file containing the OpenAI API key if OPENAI_API_KEY is unset",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.5,
        help="Delay between API calls",
    )
    parser.add_argument(
        "--daily-token-budget",
        type=int,
        default=(
            int(os.environ["EUSEBIUS_TRANSLATION_DAILY_TOKEN_BUDGET"])
            if os.environ.get("EUSEBIUS_TRANSLATION_DAILY_TOKEN_BUDGET")
            else None
        ),
        help="Maximum input+output tokens to spend today; defaults depend on --mode",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the passages that would be translated without calling OpenAI",
    )
    return parser.parse_args()


def mode_default(mode: str, key: str) -> str | int:
    return MODE_DEFAULTS[mode][key]


def resolve_model(args: argparse.Namespace) -> str:
    return args.model or str(mode_default(args.mode, "model"))


def resolve_prompt_version(args: argparse.Namespace) -> str:
    return args.prompt_version or str(mode_default(args.mode, "prompt_version"))


def resolve_daily_token_budget(args: argparse.Namespace) -> int:
    return args.daily_token_budget or int(mode_default(args.mode, "daily_token_budget"))


def configure_api_key(path_text: str) -> bool:
    if os.environ.get("OPENAI_API_KEY"):
        return True
    path = Path(path_text).expanduser()
    if path.exists():
        os.environ["OPENAI_API_KEY"] = path.read_text(encoding="utf-8").strip()
        return bool(os.environ["OPENAI_API_KEY"])
    return False


def fetch_pending_passages(
    conn: psycopg.Connection,
    *,
    mode: str,
    model: str,
    prompt_version: str,
    limit: int,
) -> list[dict[str, Any]]:
    source_filter = "AND COALESCE(p.english_text, '') <> ''" if mode == "cleanup" else ""
    rows = conn.execute(
        f"""
        SELECT p.passage_id, p.canonical_ref, p.greek_text,
               COALESCE(p.english_text, '') AS source_english
        FROM passages AS p
        WHERE TRUE
          {source_filter}
          AND NOT EXISTS (
            SELECT 1
            FROM ai_translation_runs AS r
            WHERE r.passage_id = p.passage_id
              AND r.model = %s
              AND r.prompt_version = %s
              AND r.status = 'completed'
        )
        ORDER BY
            CASE WHEN p.book ~ '^[0-9]+$' THEN p.book::int END NULLS LAST,
            p.book,
            CASE
                WHEN p.chapter = 'prologue' THEN 0
                WHEN p.chapter ~ '^[0-9]+$' THEN p.chapter::int
            END NULLS LAST,
            p.chapter,
            p.paragraph_index
        LIMIT %s
        """,
        (model, prompt_version, limit),
    ).fetchall()
    return [
        {
            "passage_id": row[0],
            "canonical_ref": row[1],
            "greek_text": row[2],
            "source_english": row[3],
        }
        for row in rows
    ]


def tokens_used_today(
    conn: psycopg.Connection,
    *,
    model: str,
    prompt_version: str,
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(input_tokens + output_tokens), 0)
        FROM ai_translation_runs
        WHERE model = %s
          AND prompt_version = %s
          AND status = 'completed'
          AND completed_at >= date_trunc('day', now())
        """,
        (model, prompt_version),
    ).fetchone()
    return int(row[0] or 0)


def estimate_request_tokens(*texts: str) -> int:
    prompt_overhead = 600
    text_chars = sum(len(text) for text in texts)
    return prompt_overhead + max(1, text_chars // 4)


def start_run(
    conn: psycopg.Connection,
    *,
    passage_id: int,
    model: str,
    prompt_version: str,
) -> int | None:
    row = conn.execute(
        """
        INSERT INTO ai_translation_runs (
            passage_id, model, prompt_version, status, requested_at,
            english_translation, notes, input_tokens, output_tokens, error_message
        )
        VALUES (%s, %s, %s, 'pending', now(), NULL, NULL, 0, 0, NULL)
        ON CONFLICT (passage_id, model, prompt_version) DO UPDATE SET
            status = 'pending',
            requested_at = now(),
            english_translation = NULL,
            notes = NULL,
            input_tokens = 0,
            output_tokens = 0,
            error_message = NULL,
            completed_at = NULL
        WHERE ai_translation_runs.status <> 'completed'
        RETURNING translation_run_id
        """,
        (passage_id, model, prompt_version),
    ).fetchone()
    conn.commit()
    return None if row is None else row[0]


def complete_run(
    conn: psycopg.Connection,
    *,
    translation_run_id: int,
    english_translation: str,
    notes: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    conn.execute(
        """
        UPDATE ai_translation_runs
        SET status = 'completed',
            english_translation = %s,
            notes = %s,
            input_tokens = %s,
            output_tokens = %s,
            error_message = NULL,
            completed_at = now()
        WHERE translation_run_id = %s
        """,
        (
            english_translation,
            notes,
            input_tokens,
            output_tokens,
            translation_run_id,
        ),
    )
    conn.commit()


def fail_run(
    conn: psycopg.Connection,
    *,
    translation_run_id: int,
    error_message: str,
) -> None:
    conn.execute(
        """
        UPDATE ai_translation_runs
        SET status = 'error',
            error_message = %s,
            completed_at = now()
        WHERE translation_run_id = %s
        """,
        (error_message[:2000], translation_run_id),
    )
    conn.commit()


def response_text(response: Any) -> str:
    direct_text = getattr(response, "output_text", None)
    if direct_text:
        return str(direct_text)
    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def usage_value(response: Any, name: str) -> int:
    usage = getattr(response, "usage", None)
    value = getattr(usage, name, 0) if usage is not None else 0
    return int(value or 0)


def create_english_text(
    client: OpenAI,
    *,
    mode: str,
    model: str,
    canonical_ref: str,
    greek_text: str,
    source_english: str,
) -> tuple[str, str, int, int]:
    if mode == "cleanup":
        system_prompt = (
            "You are cleaning an existing English reference translation of "
            "Eusebius of Caesarea's Historia Ecclesiastica. Use the Greek as "
            "a guardrail to verify alignment and meaning, but do not make a "
            "fresh translation from Greek. Fix only minor OCR, missing-letter, "
            "spacing, line-break, punctuation, and obvious alignment artifacts "
            "in the supplied English. Preserve the reference translation's "
            "wording and style where it is already serviceable. If the English "
            "looks substantially misaligned or too broken for light cleanup, "
            "return the least-invasive cleaned English you can justify and "
            "explain the concern in notes. Return JSON only."
        )
        task_text = (
            f"Canonical reference: {canonical_ref}\n\n"
            f"Greek source text:\n{greek_text}\n\n"
            f"Rough First1K English to clean:\n{source_english}\n\n"
            "Return a JSON object with keys english_translation and notes. "
            "The english_translation value should be the lightly cleaned "
            "English text, not a new translation."
        )
    else:
        system_prompt = (
            "You are a careful translator of Eusebius of Caesarea's Historia "
            "Ecclesiastica. Translate the Greek into faithful, readable English. "
            "Use any supplied First1K English only as a rough comparison source; "
            "it may contain OCR errors or alignment mistakes. Do not copy its "
            "typos. Return JSON only."
        )
        task_text = (
            f"Canonical reference: {canonical_ref}\n\n"
            f"Greek source text:\n{greek_text}\n\n"
            f"Rough First1K English reference:\n{source_english or '(none)'}\n\n"
            "Return a JSON object with keys english_translation and notes. "
            "The english_translation value should be a fresh translation from "
            "the Greek. Keep notes brief and use an empty string if there is "
            "nothing important to flag."
        )

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": task_text,
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "eusebius_translation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "english_translation": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["english_translation", "notes"],
                },
            }
        },
    )
    text = response_text(response)
    try:
        payload = json.loads(text)
        translation = str(payload.get("english_translation", "")).strip()
        notes = str(payload.get("notes", "")).strip()
    except json.JSONDecodeError:
        translation = text.strip()
        notes = "Model response was not valid JSON."
    if not translation:
        raise RuntimeError("OpenAI response did not include an English translation")
    return (
        translation,
        notes,
        usage_value(response, "input_tokens"),
        usage_value(response, "output_tokens"),
    )


def main() -> None:
    args = parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    model = resolve_model(args)
    prompt_version = resolve_prompt_version(args)
    daily_token_budget = resolve_daily_token_budget(args)

    with psycopg.connect(args.database_url) as conn:
        passages = fetch_pending_passages(
            conn,
            mode=args.mode,
            model=model,
            prompt_version=prompt_version,
            limit=args.limit,
        )
        if not passages:
            print("No passages need work for this mode, model, and prompt version.")
            return
        used_tokens = tokens_used_today(
            conn,
            model=model,
            prompt_version=prompt_version,
        )
        remaining_tokens = daily_token_budget - used_tokens

        if args.dry_run:
            print(
                f"mode={args.mode} model={model} prompt_version={prompt_version} "
                f"used_today={used_tokens} budget={daily_token_budget}"
            )
            for passage in passages:
                print(f"{passage['canonical_ref']}: passage_id={passage['passage_id']}")
            return

        if remaining_tokens <= 0:
            print(
                f"Daily token budget already exhausted for {model} "
                f"{prompt_version}: {used_tokens}/{daily_token_budget}."
            )
            return

        if not configure_api_key(args.openai_api_key_file):
            print("No OPENAI_API_KEY or readable API key file configured; no work run.")
            return

        client = OpenAI()
        completed = 0
        for passage in passages:
            estimated_tokens = estimate_request_tokens(
                passage["greek_text"],
                passage["source_english"],
            )
            if estimated_tokens > remaining_tokens:
                print(
                    f"Stopping before {passage['canonical_ref']}: estimated "
                    f"{estimated_tokens} tokens but only {remaining_tokens} remain."
                )
                break
            run_id = start_run(
                conn,
                passage_id=passage["passage_id"],
                model=model,
                prompt_version=prompt_version,
            )
            if run_id is None:
                continue
            try:
                translation, notes, input_tokens, output_tokens = create_english_text(
                    client,
                    mode=args.mode,
                    model=model,
                    canonical_ref=passage["canonical_ref"],
                    greek_text=passage["greek_text"],
                    source_english=passage["source_english"],
                )
                complete_run(
                    conn,
                    translation_run_id=run_id,
                    english_translation=translation,
                    notes=notes,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                completed += 1
                spent_tokens = input_tokens + output_tokens
                remaining_tokens -= spent_tokens
                print(
                    f"Completed {args.mode} for {passage['canonical_ref']} "
                    f"tokens={input_tokens}/{output_tokens} "
                    f"remaining_budget={max(0, remaining_tokens)}"
                )
            except Exception as exc:  # noqa: BLE001 - persist API/schema failures.
                fail_run(conn, translation_run_id=run_id, error_message=str(exc))
                print(f"Failed {passage['canonical_ref']}: {exc}")
            time.sleep(args.delay_seconds)

    print(f"Completed {completed} {args.mode} run(s).")


if __name__ == "__main__":
    main()
