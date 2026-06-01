#!/usr/bin/env python
"""Score Eusebius passages for documentary-comic planning."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from typing import Iterable

import psycopg


SCORING_VERSION = "deterministic-comic-v1"


@dataclass(frozen=True)
class FeatureGroup:
    """A set of source terms that contributes one explainable score component."""

    name: str
    weight: float
    terms: tuple[str, ...]


FEATURE_GROUPS = (
    FeatureGroup(
        name="places",
        weight=2.0,
        terms=(
            "alexandria",
            "antioch",
            "caesarea",
            "egypt",
            "jerusalem",
            "judea",
            "nicomedia",
            "palestine",
            "rome",
            "syria",
        ),
    ),
    FeatureGroup(
        name="office and succession",
        weight=1.5,
        terms=("apostle", "bishop", "church", "presbyter", "succession"),
    ),
    FeatureGroup(
        name="imperial power",
        weight=1.8,
        terms=("caesar", "constantine", "emperor", "imperial", "king", "magistrate"),
    ),
    FeatureGroup(
        name="conflict and persecution",
        weight=2.2,
        terms=(
            "accuse",
            "banish",
            "court",
            "death",
            "fire",
            "martyr",
            "persecution",
            "prison",
            "soldier",
            "suffer",
            "trial",
        ),
    ),
    FeatureGroup(
        name="documents and testimony",
        weight=1.7,
        terms=(
            "decree",
            "epistle",
            "letter",
            "proclamation",
            "record",
            "testimony",
            "wrote",
            "written",
        ),
    ),
    FeatureGroup(
        name="visual action",
        weight=1.4,
        terms=("assembled", "crowd", "fled", "journey", "sailed", "sent", "ship", "travel"),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("EUSEBIUS_DATABASE_URL", "postgresql:///eusebius"),
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--scoring-version",
        default=os.environ.get("EUSEBIUS_COMIC_SCORING_VERSION", SCORING_VERSION),
        help="Version label stored in comic_candidates",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("EUSEBIUS_COMIC_SCORE_LIMIT", "0")),
        help="Maximum unscored passages to inspect; 0 means all",
    )
    parser.add_argument(
        "--minimum-score",
        type=float,
        default=float(os.environ.get("EUSEBIUS_COMIC_MINIMUM_SCORE", "3.0")),
        help="Minimum score to store as a comic candidate",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print scored candidates without writing to PostgreSQL",
    )
    return parser.parse_args()


def normalize_text(*parts: str) -> str:
    return " ".join(part.casefold() for part in parts if part)


def term_count(text: str, term: str) -> int:
    pattern = rf"\b{re.escape(term.casefold())}\w*\b"
    return len(re.findall(pattern, text))


def score_passage(
    *,
    greek_text: str,
    english_text: str,
    ai_english_translation: str,
) -> tuple[float, str]:
    """Return an explainable comic-candidate score and short reason."""

    text = normalize_text(english_text, ai_english_translation)
    score = 0.0
    reasons: list[str] = []

    for group in FEATURE_GROUPS:
        matches = sorted({term for term in group.terms if term_count(text, term)})
        if matches:
            contribution = group.weight * min(3, len(matches))
            score += contribution
            reasons.append(f"{group.name}: {', '.join(matches[:5])}")

    greek_length_bonus = min(1.0, max(0.0, len(greek_text) / 1800))
    if greek_length_bonus:
        score += greek_length_bonus

    if not reasons:
        return (0.0, "No documentary-comic features matched.")

    return (round(score, 2), "; ".join(reasons))


def fetch_unscored_passages(
    conn: psycopg.Connection,
    *,
    scoring_version: str,
    limit: int,
) -> list[dict]:
    limit_clause = "LIMIT %s" if limit > 0 else ""
    params: list[object] = [scoring_version]
    if limit > 0:
        params.append(limit)
    rows = conn.execute(
        f"""
        SELECT p.passage_id, p.canonical_ref, p.greek_text,
               COALESCE(p.english_text, '') AS english_text,
               COALESCE(tr.english_translation, '') AS ai_english_translation
        FROM passages AS p
        LEFT JOIN LATERAL (
            SELECT english_translation
            FROM ai_translation_runs
            WHERE ai_translation_runs.passage_id = p.passage_id
              AND ai_translation_runs.status = 'completed'
              AND ai_translation_runs.english_translation IS NOT NULL
            ORDER BY completed_at DESC NULLS LAST, translation_run_id DESC
            LIMIT 1
        ) AS tr ON TRUE
        WHERE NOT EXISTS (
            SELECT 1
            FROM comic_candidates AS c
            WHERE c.passage_id = p.passage_id
              AND c.scoring_version = %s
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
        {limit_clause}
        """,
        params,
    ).fetchall()
    return [
        {
            "passage_id": row[0],
            "canonical_ref": row[1],
            "greek_text": row[2],
            "english_text": row[3],
            "ai_english_translation": row[4],
        }
        for row in rows
    ]


def store_candidates(
    conn: psycopg.Connection,
    candidates: Iterable[tuple[int, float, str, str]],
    *,
    scoring_version: str,
) -> int:
    stored = 0
    for passage_id, candidate_score, reason, status in candidates:
        conn.execute(
            """
            INSERT INTO comic_candidates (
                passage_id, candidate_score, reason, status, scoring_version
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (passage_id, scoring_version) DO UPDATE SET
                candidate_score = EXCLUDED.candidate_score,
                reason = EXCLUDED.reason,
                status = EXCLUDED.status
            """,
            (passage_id, candidate_score, reason, status, scoring_version),
        )
        stored += 1
    conn.commit()
    return stored


def main() -> None:
    args = parse_args()
    with psycopg.connect(args.database_url) as conn:
        rows = fetch_unscored_passages(
            conn,
            scoring_version=args.scoring_version,
            limit=args.limit,
        )
        candidates = []
        for row in rows:
            score, reason = score_passage(
                greek_text=row["greek_text"],
                english_text=row["english_text"],
                ai_english_translation=row["ai_english_translation"],
            )
            if score >= args.minimum_score:
                candidates.append(
                    (row["passage_id"], score, reason, "candidate", row["canonical_ref"])
                )

        if args.dry_run:
            for _passage_id, score, reason, _status, canonical_ref in candidates:
                print(f"{canonical_ref}\t{score:.2f}\t{reason}")
            print(f"Would store {len(candidates)} candidate(s) from {len(rows)} passage(s).")
            return

        stored = store_candidates(
            conn,
            (
                (passage_id, score, reason, status)
                for passage_id, score, reason, status, _canonical_ref in candidates
            ),
            scoring_version=args.scoring_version,
        )
        print(f"Stored {stored} candidate(s) from {len(rows)} passage(s).")


if __name__ == "__main__":
    main()
