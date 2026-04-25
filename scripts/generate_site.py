#!/usr/bin/env python
"""Generate a small static Eusebius research site from PostgreSQL."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import psycopg


GREEK_STOPWORDS = {
    "και", "δε", "το", "τα", "των", "τησ", "τω", "τον", "την", "του", "τοισ",
    "τουσ", "τασ", "ταισ", "οι", "εν", "εισ", "γαρ", "μεν", "τε", "ωσ", "ου",
    "τη", "τηι", "τωι", "απο", "προσ", "δια", "επι", "η", "κατα", "περι",
    "μετα", "παρα", "υπο", "ουν", "οτι", "καθ", "κατ", "αυτου", "αυτων",
    "αυτον", "αυτω", "αυτωι", "αυτοισ", "αυτοσ", "αυτουσ", "ταυτα",
    "τουτο", "τουτων", "τουτοισ", "ημων", "ημιν", "ημασ", "τισ", "τινα",
    "τινων", "τινοσ", "τινι", "τινεσ", "αλλα", "ουκ", "μην", "ειναι",
    "ηδη", "ετι", "τοτε", "αλλ", "προ", "νυν", "παρ", "υπερ",
}

RESEARCH_IDEAS = [
    (
        "Transport-weighted place network",
        "Do nearby coastal cities co-occur differently from inland places, and does sea access predict narrative centrality?",
    ),
    (
        "Apostolic succession as graph compression",
        "How much of the narrative can be explained by bishop-to-bishop succession chains, and where does Eusebius break that chain for polemic or crisis?",
    ),
    (
        "Persecution geography",
        "Are persecution episodes clustered by province, imperial center, or communication corridor?",
    ),
    (
        "Authority-source switching",
        "When Eusebius moves between scripture, Josephus, letters, archives, and named historians, does the local vocabulary or certainty marking change?",
    ),
    (
        "Citation distance",
        "Do quoted authorities appear near the places and people they discuss, or does Eusebius use geographically remote authorities for particular arguments?",
    ),
    (
        "Imperial proximity",
        "Do mentions of emperors correlate with Rome, Nicomedia, Antioch, and other administrative centers, and does that change across books?",
    ),
    (
        "Heresy and network periphery",
        "Are heresiarchs and disputed teachers structurally peripheral in the co-occurrence graph, or are they central bridges between orthodox figures?",
    ),
    (
        "Martyrdom narrative signatures",
        "Can martyrdom passages be separated by transparent lexical and entity features without using a black-box classifier?",
    ),
    (
        "Chronological density",
        "Which books compress the most years per passage, and which slow down into document-heavy narrative?",
    ),
    (
        "Epistolary infrastructure",
        "Do letters and decrees link different regions than narrative prose does, suggesting a documentary communication network?",
    ),
    (
        "Classical versus biblical geography",
        "Are biblical places, Greek cities, and Roman administrative centers used in different argumentative contexts?",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("EUSEBIUS_DATABASE_URL", "postgresql:///eusebius"),
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--output-dir",
        default="eusebius_site",
        help="Directory to write static site files",
    )
    return parser.parse_args()


def greek_tokens(text: str) -> list[str]:
    tokens = []
    for raw_token in re.findall(r"[Α-ωἀ-῾]+", text):
        decomposed = unicodedata.normalize("NFD", raw_token.casefold())
        token = "".join(
            char for char in decomposed if unicodedata.category(char) != "Mn"
        ).replace("ς", "σ")
        if len(token) > 2 and token not in GREEK_STOPWORDS:
            tokens.append(token)
    return tokens


def fetch_rows(conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT canonical_ref, book, chapter, paragraph_index,
               greek_text, COALESCE(english_text, '') AS english_text,
               greek_word_count, english_word_count
        FROM passages
        ORDER BY book::int NULLS LAST, chapter, paragraph_index
        """
    ).fetchall()
    return [
        {
            "canonical_ref": row[0],
            "book": row[1],
            "chapter": row[2],
            "paragraph_index": row[3],
            "greek_text": row[4],
            "english_text": row[5],
            "greek_word_count": row[6],
            "english_word_count": row[7],
        }
        for row in rows
    ]


def fetch_source(conn: psycopg.Connection) -> dict:
    row = conn.execute(
        """
        SELECT title, source_url, cts_urn, edition_note, license_note,
               raw_sha256, raw_bytes, fetched_at
        FROM sources
        WHERE source_id = 'first1k-tlg2018-tlg002-grc1'
        """
    ).fetchone()
    if row is None:
        return {}
    return {
        "title": row[0],
        "source_url": row[1],
        "cts_urn": row[2],
        "edition_note": row[3],
        "license_note": row[4],
        "raw_sha256": row[5],
        "raw_bytes": row[6],
        "fetched_at": row[7],
    }


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def render_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <nav>
      <a href="index.html">Status</a>
      <a href="passages.html">Passages</a>
      <a href="research.html">Research Questions</a>
      <a href="data/top_terms.json">Data</a>
    </nav>
  </header>
  <main>
{body}
  </main>
</body>
</html>
"""


def generate(output_dir: Path, rows: list[dict], source: dict) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "assets").mkdir(parents=True)
    (output_dir / "data").mkdir(parents=True)

    token_counts: Counter[str] = Counter()
    book_word_counts: defaultdict[str, int] = defaultdict(int)
    chapter_counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        token_counts.update(greek_tokens(row["greek_text"]))
        book_word_counts[row["book"]] += row["greek_word_count"]
        chapter_counts[row["book"]] += 1

    top_terms = token_counts.most_common(100)
    write_text(
        output_dir / "data" / "top_terms.json",
        json.dumps(
            [{"term": term, "count": count} for term, count in top_terms],
            ensure_ascii=False,
            indent=2,
        ),
    )

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    fetched_at = source.get("fetched_at")
    if fetched_at:
        fetched_at = fetched_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")

    book_rows = "\n".join(
        f"<tr><td>{html.escape(book)}</td><td>{chapter_counts[book]}</td><td>{book_word_counts[book]}</td></tr>"
        for book in sorted(book_word_counts, key=lambda value: int(value))
    )
    term_items = "\n".join(
        f"<li><span lang='grc'>{html.escape(term)}</span> <b>{count}</b></li>"
        for term, count in top_terms[:30]
    )

    index_body = f"""
    <section>
      <h2>Corpus</h2>
      <p>This is a deliberately small, non-OpenAI baseline for Eusebius' <i>Historia Ecclesiastica</i>.
      The site is generated from PostgreSQL on <code>raksasa</code> and published statically to <code>merah</code>.</p>
      <dl>
        <dt>Passages</dt><dd>{len(rows)}</dd>
        <dt>Greek words</dt><dd>{sum(row["greek_word_count"] for row in rows)}</dd>
        <dt>Source</dt><dd><a href="{html.escape(source.get("source_url", "#"))}">{html.escape(source.get("cts_urn", ""))}</a></dd>
        <dt>Edition</dt><dd>{html.escape(source.get("edition_note", ""))}</dd>
        <dt>License note</dt><dd>{html.escape(source.get("license_note", ""))}</dd>
        <dt>Fetched</dt><dd>{html.escape(str(fetched_at or "unknown"))}</dd>
        <dt>Generated</dt><dd>{generated_at}</dd>
      </dl>
    </section>
    <section>
      <h2>Book Scale</h2>
      <table><thead><tr><th>Book</th><th>Passages</th><th>Greek words</th></tr></thead><tbody>{book_rows}</tbody></table>
    </section>
    <section>
      <h2>Top Greek Terms</h2>
      <ol class="terms">{term_items}</ol>
    </section>
    """
    write_text(output_dir / "index.html", render_page("Eusebius Research Baseline", index_body))

    idea_rows = "\n".join(
        f"<article><h2>{html.escape(title)}</h2><p>{html.escape(question)}</p></article>"
        for title, question in RESEARCH_IDEAS
    )
    research_body = f"""
    <p>These questions are meant to stay explainable: the first pass should use transparent
    counts, co-occurrence graphs, distances, source labels, and simple regression models before any LLM-generated labels.</p>
    {idea_rows}
    """
    write_text(output_dir / "research.html", render_page("Eusebius Research Questions", research_body))

    passage_items = []
    for row in rows[:250]:
        passage_items.append(
            f"""
            <article class="passage" id="p-{html.escape(row["canonical_ref"])}">
              <h2>{html.escape(row["canonical_ref"])}</h2>
              <p lang="grc">{html.escape(row["greek_text"])}</p>
              <p>{html.escape(row["english_text"] or "No aligned English text imported for this paragraph.")}</p>
            </article>
            """
        )
    passages_body = "\n".join(passage_items)
    if len(rows) > 250:
        passages_body += f"<p class='note'>Showing the first 250 of {len(rows)} imported passages.</p>"
    write_text(output_dir / "passages.html", render_page("Eusebius Passages", passages_body))

    write_text(
        output_dir / "assets" / "style.css",
        """
body {
  margin: 0;
  color: #1d2329;
  background: #f7f7f4;
  font: 16px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
header {
  background: #27313a;
  color: white;
  padding: 1.2rem max(1rem, calc((100vw - 980px) / 2));
}
h1 { margin: 0 0 .5rem; font-size: clamp(1.8rem, 4vw, 3rem); }
nav { display: flex; gap: 1rem; flex-wrap: wrap; }
nav a { color: #dce9f7; }
main { max-width: 980px; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
section, article { border-top: 1px solid #d7d2c8; padding: 1.2rem 0; }
h2 { margin: 0 0 .55rem; font-size: 1.25rem; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .35rem 1rem; }
dt { font-weight: 700; }
table { border-collapse: collapse; width: 100%; background: white; }
th, td { border: 1px solid #d7d2c8; padding: .45rem .6rem; text-align: left; }
.terms { columns: 2; }
.terms li { break-inside: avoid; }
.passage p[lang="grc"] { font-size: 1.08rem; }
.note { color: #5a646d; }
@media (max-width: 680px) {
  dl { grid-template-columns: 1fr; }
  .terms { columns: 1; }
}
""".strip()
        + "\n",
    )


def main() -> None:
    args = parse_args()
    with psycopg.connect(args.database_url) as conn:
        rows = fetch_rows(conn)
        source = fetch_source(conn)
    generate(Path(args.output_dir), rows, source)
    print(f"Generated {args.output_dir} with {len(rows)} passages")


if __name__ == "__main__":
    main()
