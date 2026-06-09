#!/usr/bin/env python
"""Plan queued documentary-comic panels from scored Eusebius candidates."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import psycopg
from openai import OpenAI


DEFAULT_MODEL = "gpt-5.5"
DEFAULT_PROMPT_VERSION = "documentary-comic-plan-v1"
DEFAULT_DAILY_TOKEN_BUDGET = 10_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("EUSEBIUS_DATABASE_URL", "postgresql:///eusebius"),
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("EUSEBIUS_COMIC_PLAN_MODEL", DEFAULT_MODEL),
        help="OpenAI text model for planning",
    )
    parser.add_argument(
        "--prompt-version",
        default=os.environ.get(
            "EUSEBIUS_COMIC_PLAN_PROMPT_VERSION", DEFAULT_PROMPT_VERSION
        ),
        help="Prompt version stored with comic_plans",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("EUSEBIUS_COMIC_PLAN_LIMIT", "1")),
        help="Maximum candidates to plan",
    )
    parser.add_argument(
        "--minimum-score",
        type=float,
        default=float(os.environ.get("EUSEBIUS_COMIC_PLAN_MINIMUM_SCORE", "6.0")),
        help="Minimum candidate score to inspect",
    )
    parser.add_argument(
        "--daily-token-budget",
        type=int,
        default=int(
            os.environ.get(
                "EUSEBIUS_COMIC_PLAN_DAILY_TOKEN_BUDGET",
                str(DEFAULT_DAILY_TOKEN_BUDGET),
            )
        ),
        help="Maximum input+output tokens to spend today",
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
        "--dry-run",
        action="store_true",
        help="Print candidate rows without calling OpenAI or writing plans",
    )
    return parser.parse_args()


def configure_api_key(path_text: str) -> bool:
    if os.environ.get("OPENAI_API_KEY"):
        return True
    path = Path(path_text).expanduser()
    if path.exists():
        os.environ["OPENAI_API_KEY"] = path.read_text(encoding="utf-8").strip()
        return bool(os.environ["OPENAI_API_KEY"])
    return False


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


def estimate_request_tokens(candidate: dict[str, Any]) -> int:
    text_chars = sum(
        len(str(candidate.get(key, "")))
        for key in ("canonical_ref", "greek_text", "english_text", "translation")
    )
    return 1_200 + max(1, text_chars // 4)


def tokens_used_today(
    conn: psycopg.Connection,
    *,
    model: str,
    prompt_version: str,
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(input_tokens + output_tokens), 0)
        FROM comic_plans
        WHERE model = %s
          AND prompt_version = %s
          AND status IN ('planned', 'rendering', 'done')
          AND created_at >= date_trunc('day', now())
        """,
        (model, prompt_version),
    ).fetchone()
    return int(row[0] or 0)


def fetch_candidates(
    conn: psycopg.Connection,
    *,
    minimum_score: float,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.comic_candidate_id, c.passage_id, c.candidate_score,
               c.reason, c.scoring_version, p.canonical_ref, p.greek_text,
               COALESCE(p.english_text, '') AS english_text,
               tr.translation_run_id,
               COALESCE(tr.english_translation, '') AS translation
        FROM comic_candidates AS c
        JOIN passages AS p USING (passage_id)
        LEFT JOIN LATERAL (
            SELECT translation_run_id, english_translation
            FROM ai_translation_runs
            WHERE ai_translation_runs.passage_id = p.passage_id
              AND ai_translation_runs.status = 'completed'
              AND ai_translation_runs.english_translation IS NOT NULL
            ORDER BY completed_at DESC NULLS LAST, translation_run_id DESC
            LIMIT 1
        ) AS tr ON TRUE
        WHERE c.status = 'candidate'
          AND c.candidate_score >= %s
          AND NOT EXISTS (
              SELECT 1
              FROM comic_plans AS cp
              WHERE cp.passage_id = c.passage_id
                AND cp.status IN ('planned', 'rendering', 'done')
          )
        ORDER BY c.candidate_score DESC, c.comic_candidate_id
        LIMIT %s
        """,
        (minimum_score, limit),
    ).fetchall()
    return [
        {
            "comic_candidate_id": row[0],
            "passage_id": row[1],
            "candidate_score": float(row[2]),
            "reason": row[3],
            "scoring_version": row[4],
            "canonical_ref": row[5],
            "greek_text": row[6],
            "english_text": row[7],
            "translation_run_id": row[8],
            "translation": row[9],
        }
        for row in rows
    ]


def plan_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {"type": "string", "enum": ["plan", "reject"]},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "rejection_reason": {"type": "string"},
            "continuity_notes": {"type": "string"},
            "panels": {
                "type": "array",
                "minItems": 0,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "panel_number": {"type": "integer", "minimum": 1, "maximum": 4},
                        "panel_title": {"type": "string"},
                        "panel_prompt": {"type": "string"},
                        "caption": {"type": "string"},
                    },
                    "required": [
                        "panel_number",
                        "panel_title",
                        "panel_prompt",
                        "caption",
                    ],
                },
            },
        },
        "required": [
            "decision",
            "title",
            "summary",
            "rejection_reason",
            "continuity_notes",
            "panels",
        ],
    }


def validate_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate a planning response before storing it."""

    decision = str(payload.get("decision", "")).strip()
    if decision not in {"plan", "reject"}:
        raise ValueError("planning response decision must be 'plan' or 'reject'")

    title = str(payload.get("title", "")).strip()
    summary = str(payload.get("summary", "")).strip()
    rejection_reason = str(payload.get("rejection_reason", "")).strip()
    continuity_notes = str(payload.get("continuity_notes", "")).strip()
    panels = payload.get("panels", [])
    if not isinstance(panels, list):
        raise ValueError("planning response panels must be a list")

    normalized_panels: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError("each panel must be an object")
        panel_number = int(panel.get("panel_number", 0))
        panel_title = str(panel.get("panel_title", "")).strip()
        panel_prompt = str(panel.get("panel_prompt", "")).strip()
        caption = str(panel.get("caption", "")).strip()
        if panel_number < 1 or panel_number > 4:
            raise ValueError("panel_number must be between 1 and 4")
        if panel_number in seen_numbers:
            raise ValueError("panel_number values must be unique")
        if not panel_title or not panel_prompt:
            raise ValueError("planned panels require title and prompt")
        if len(caption) > 180:
            raise ValueError("panel captions must stay short")
        seen_numbers.add(panel_number)
        normalized_panels.append(
            {
                "panel_number": panel_number,
                "panel_title": panel_title,
                "panel_prompt": panel_prompt,
                "caption": caption,
            }
        )

    normalized_panels.sort(key=lambda panel: panel["panel_number"])
    if decision == "plan":
        if not title or not summary:
            raise ValueError("accepted plans require title and summary")
        if not 2 <= len(normalized_panels) <= 4:
            raise ValueError("accepted plans require 2 to 4 panels")
    elif not rejection_reason:
        raise ValueError("rejected plans require a rejection_reason")

    return {
        "decision": decision,
        "title": title or "Rejected comic candidate",
        "summary": summary,
        "rejection_reason": rejection_reason,
        "continuity_notes": continuity_notes,
        "panels": normalized_panels,
    }


def create_plan(
    client: OpenAI,
    *,
    model: str,
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    source_english = candidate["translation"] or candidate["english_text"]
    system_prompt = (
        "You plan source-grounded documentary-comic panels for Eusebius of "
        "Caesarea's Historia Ecclesiastica. Accept only passages with concrete "
        "visual documentary value. Reject abstract theology, repetitive lists, "
        "and passages that cannot be drawn without inventing events. For accepted "
        "plans, write image prompts for comic panels that can include short, "
        "legible, source-grounded labels, captions, map callouts, or title text "
        "inside the image when that helps the panel make sense. Avoid long Greek "
        "or English passages, dense paragraphs, and invented dialogue. Use visual "
        "historical cues, manuscripts, maps, bishops, imperial officials, travel, "
        "courtroom, prison, council, or letter-delivery imagery only when grounded "
        "in the source text. Return JSON only."
    )
    task_text = (
        f"Canonical reference: {candidate['canonical_ref']}\n"
        f"Candidate score: {candidate['candidate_score']}\n"
        f"Deterministic reason: {candidate['reason']}\n\n"
        f"Greek source text:\n{candidate['greek_text']}\n\n"
        f"English source text:\n{source_english}\n\n"
        "Return a JSON object. If accepted, create 2 to 4 panels. Each "
        "panel_prompt must be detailed enough for an image model. It may include "
        "short readable labels or captions inside the artwork when they clarify "
        "the scene, but it must not ask for long blocks of text or invented "
        "speech. Captions should still be concise so they can also be displayed "
        "outside the image in the comic viewer."
    )
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_text},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "eusebius_comic_plan",
                "strict": True,
                "schema": plan_schema(),
            }
        },
    )
    payload = validate_plan_payload(json.loads(response_text(response)))
    return (
        payload,
        usage_value(response, "input_tokens"),
        usage_value(response, "output_tokens"),
    )


def store_plan(
    conn: psycopg.Connection,
    *,
    candidate: dict[str, Any],
    model: str,
    prompt_version: str,
    payload: dict[str, Any],
    input_tokens: int,
    output_tokens: int,
) -> int | None:
    if payload["decision"] == "reject":
        conn.execute(
            """
            UPDATE comic_candidates
            SET status = 'rejected'
            WHERE comic_candidate_id = %s
            """,
            (candidate["comic_candidate_id"],),
        )
        conn.commit()
        return None

    row = conn.execute(
        """
        INSERT INTO comic_plans (
            passage_id, translation_run_id, model, prompt_version, title, summary,
            plan_json, status, input_tokens, output_tokens, error_message
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 'planned', %s, %s, NULL)
        RETURNING comic_plan_id
        """,
        (
            candidate["passage_id"],
            candidate["translation_run_id"],
            model,
            prompt_version,
            payload["title"],
            payload["summary"],
            json.dumps(payload, ensure_ascii=False),
            input_tokens,
            output_tokens,
        ),
    ).fetchone()
    comic_plan_id = int(row[0])
    for panel in payload["panels"]:
        conn.execute(
            """
            INSERT INTO comic_panels (
                comic_plan_id, panel_number, panel_title, panel_prompt, caption,
                negative_prompt, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'queued')
            ON CONFLICT (comic_plan_id, panel_number) DO UPDATE SET
                panel_title = EXCLUDED.panel_title,
                panel_prompt = EXCLUDED.panel_prompt,
                caption = EXCLUDED.caption,
                negative_prompt = EXCLUDED.negative_prompt,
                status = 'queued'
            """,
            (
                comic_plan_id,
                panel["panel_number"],
                panel["panel_title"],
                panel["panel_prompt"],
                panel["caption"],
                "readable text, captions, speech balloons, modern typography",
            ),
        )
    conn.execute(
        """
        UPDATE comic_candidates
        SET status = 'planned'
        WHERE comic_candidate_id = %s
        """,
        (candidate["comic_candidate_id"],),
    )
    conn.commit()
    return comic_plan_id


def main() -> None:
    args = parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")

    with psycopg.connect(args.database_url) as conn:
        candidates = fetch_candidates(
            conn,
            minimum_score=args.minimum_score,
            limit=args.limit,
        )
        if not candidates:
            print("No comic candidates need planning.")
            return
        used_tokens = tokens_used_today(
            conn,
            model=args.model,
            prompt_version=args.prompt_version,
        )
        remaining_tokens = args.daily_token_budget - used_tokens

        if args.dry_run:
            print(
                f"model={args.model} prompt_version={args.prompt_version} "
                f"used_today={used_tokens} budget={args.daily_token_budget}"
            )
            for candidate in candidates:
                print(
                    f"{candidate['canonical_ref']}: "
                    f"candidate_id={candidate['comic_candidate_id']} "
                    f"score={candidate['candidate_score']:.2f}"
                )
            return

        if remaining_tokens <= 0:
            print(
                f"Daily token budget already exhausted for {args.model} "
                f"{args.prompt_version}: {used_tokens}/{args.daily_token_budget}."
            )
            return
        if not configure_api_key(args.openai_api_key_file):
            print("No OPENAI_API_KEY or readable API key file configured; no work run.")
            return

        client = OpenAI()
        planned = 0
        rejected = 0
        for candidate in candidates:
            estimated_tokens = estimate_request_tokens(candidate)
            if estimated_tokens > remaining_tokens:
                print(
                    f"Stopping before {candidate['canonical_ref']}: estimated "
                    f"{estimated_tokens} tokens but only {remaining_tokens} remain."
                )
                break
            try:
                payload, input_tokens, output_tokens = create_plan(
                    client,
                    model=args.model,
                    candidate=candidate,
                )
                comic_plan_id = store_plan(
                    conn,
                    candidate=candidate,
                    model=args.model,
                    prompt_version=args.prompt_version,
                    payload=payload,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                spent_tokens = input_tokens + output_tokens
                remaining_tokens -= spent_tokens
                if comic_plan_id is None:
                    rejected += 1
                    print(
                        f"Rejected {candidate['canonical_ref']} "
                        f"tokens={input_tokens}/{output_tokens} "
                        f"remaining_budget={max(0, remaining_tokens)}"
                    )
                else:
                    planned += 1
                    print(
                        f"Planned {candidate['canonical_ref']} "
                        f"comic_plan_id={comic_plan_id} "
                        f"tokens={input_tokens}/{output_tokens} "
                        f"remaining_budget={max(0, remaining_tokens)}"
                    )
            except Exception as exc:  # noqa: BLE001 - surface model/schema failures.
                conn.execute(
                    """
                    UPDATE comic_candidates
                    SET status = 'candidate'
                    WHERE comic_candidate_id = %s
                    """,
                    (candidate["comic_candidate_id"],),
                )
                conn.commit()
                print(f"Failed {candidate['canonical_ref']}: {exc}")
            time.sleep(args.delay_seconds)

    print(f"Planned {planned} candidate(s); rejected {rejected} candidate(s).")


if __name__ == "__main__":
    main()
