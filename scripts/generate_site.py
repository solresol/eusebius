#!/usr/bin/env python
"""Generate a small static Eusebius research site from PostgreSQL."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

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
    parser.add_argument(
        "--comic-web-dir",
        default=os.environ.get(
            "EUSEBIUS_COMIC_WEB_DIR",
            "/home/eusebius/eusebius-comic/web",
        ),
        help="Directory containing optimized comic derivatives by plan/panel",
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


def numeric_label_sort_key(value: str) -> tuple[int, int | str]:
    if value == "prologue":
        return (0, 0)
    if value.isdigit():
        return (1, int(value))
    return (2, value)


def book_sort_key(value: str) -> tuple[int, int | str]:
    if value.isdigit():
        return (0, int(value))
    return (1, value)


def slug(value: str) -> str:
    slug_text = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug_text or "unknown"


def book_page_name(book: str) -> str:
    return f"passages-book-{slug(book)}.html"


def section_page_name(book: str, section: str) -> str:
    return f"passages-book-{slug(book)}-section-{slug(section)}.html"


def section_label(section: str) -> str:
    return "Prologue" if section == "prologue" else f"Section {section}"


def group_by_book(rows: Iterable[dict]) -> dict[str, list[dict]]:
    books: defaultdict[str, list[dict]] = defaultdict(list)
    for row in rows:
        books[row["book"]].append(row)
    return dict(books)


def group_by_section(rows: Iterable[dict]) -> dict[str, list[dict]]:
    sections: defaultdict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sections[row["chapter"]].append(row)
    return dict(sections)


def fetch_rows(conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT canonical_ref, book, chapter, paragraph_index,
               greek_text, COALESCE(english_text, '') AS english_text,
               greek_word_count, english_word_count,
               COALESCE(tr.english_translation, '') AS ai_english_translation,
               COALESCE(tr.model, '') AS ai_translation_model,
               COALESCE(tr.prompt_version, '') AS ai_translation_prompt_version,
               tr.completed_at AS ai_translation_completed_at
        FROM passages
        LEFT JOIN LATERAL (
            SELECT english_translation, model, prompt_version, completed_at
            FROM ai_translation_runs
            WHERE ai_translation_runs.passage_id = passages.passage_id
              AND ai_translation_runs.status = 'completed'
              AND ai_translation_runs.english_translation IS NOT NULL
            ORDER BY completed_at DESC NULLS LAST, translation_run_id DESC
            LIMIT 1
        ) AS tr ON TRUE
        ORDER BY
            CASE WHEN book ~ '^[0-9]+$' THEN book::int END NULLS LAST,
            book,
            CASE
                WHEN chapter = 'prologue' THEN 0
                WHEN chapter ~ '^[0-9]+$' THEN chapter::int
            END NULLS LAST,
            chapter,
            paragraph_index
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
            "ai_english_translation": row[8],
            "ai_translation_model": row[9],
            "ai_translation_prompt_version": row[10],
            "ai_translation_completed_at": row[11],
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


def fetch_comic_rows(conn: psycopg.Connection) -> list[dict]:
    """Fetch rendered panels and their source/provenance for the comic viewer."""
    rows = conn.execute(
        """
        SELECT cp.comic_plan_id, cp.title, cp.summary,
               p.panel_number, p.panel_title, p.caption,
               a.public_path, a.model, a.sha256,
               pa.canonical_ref, pa.book, pa.chapter,
               COALESCE(tr.english_translation, pa.english_text, '') AS english_text,
               COALESCE(tr.model, '') AS translation_model,
               COALESCE(tr.prompt_version, '') AS translation_prompt_version
        FROM comic_plans cp
        JOIN comic_panels p USING (comic_plan_id)
        JOIN passages pa USING (passage_id)
        JOIN LATERAL (
            SELECT public_path, model, sha256
            FROM comic_image_assets
            WHERE comic_image_assets.comic_panel_id = p.comic_panel_id
              AND comic_image_assets.status = 'generated'
              AND comic_image_assets.public_path IS NOT NULL
            ORDER BY comic_image_asset_id DESC
            LIMIT 1
        ) a ON TRUE
        LEFT JOIN LATERAL (
            SELECT english_translation, model, prompt_version
            FROM ai_translation_runs
            WHERE ai_translation_runs.passage_id = pa.passage_id
              AND ai_translation_runs.status = 'completed'
              AND ai_translation_runs.english_translation IS NOT NULL
            ORDER BY completed_at DESC NULLS LAST, translation_run_id DESC
            LIMIT 1
        ) tr ON TRUE
        WHERE p.status = 'rendered'
        ORDER BY cp.comic_plan_id, p.panel_number
        """
    ).fetchall()
    return [
        {
            "comic_plan_id": row[0],
            "plan_title": row[1],
            "plan_summary": row[2],
            "panel_number": row[3],
            "panel_title": row[4],
            "caption": row[5],
            "public_path": row[6],
            "image_model": row[7],
            "image_sha256": row[8],
            "canonical_ref": row[9],
            "book": row[10],
            "chapter": row[11],
            "english_text": row[12],
            "translation_model": row[13],
            "translation_prompt_version": row[14],
        }
        for row in rows
    ]


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
      <a href="comics.html">Documentary Comic</a>
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


def render_translation_block(row: dict) -> str:
    if row["ai_english_translation"]:
        completed_at = row["ai_translation_completed_at"]
        if completed_at:
            completed_at = completed_at.astimezone(UTC).strftime("%Y-%m-%d")
        completed_suffix = f", {completed_at}" if completed_at else ""
        prompt_version = row["ai_translation_prompt_version"]
        if prompt_version.startswith("english-cleanup"):
            label = "AI English cleanup"
        elif prompt_version.startswith("greek-translation"):
            label = "AI Greek translation"
        else:
            label = "AI English text"
        return f"""
              <p class="translation-meta">{label}, {html.escape(row["ai_translation_model"])}{completed_suffix}</p>
              <p>{html.escape(row["ai_english_translation"])}</p>
        """

    source_reference = ""
    if row["english_text"]:
        source_reference = f"""
              <details>
                <summary>First1K English reference (rough OCR/alignment source)</summary>
                <p>{html.escape(row["english_text"])}</p>
              </details>
        """
    return f"""
              <p class="note">No clean AI English text has been generated for this passage yet.</p>
              {source_reference}
    """


def ref_range(rows: list[dict]) -> str:
    if not rows:
        return ""
    first_ref = rows[0]["canonical_ref"]
    last_ref = rows[-1]["canonical_ref"]
    if first_ref == last_ref:
        return first_ref
    return f"{first_ref}-{last_ref}"


def render_passage_browser(output_dir: Path, rows: list[dict]) -> None:
    books = group_by_book(rows)
    sorted_books = sorted(books, key=book_sort_key)

    book_items = []
    for book in sorted_books:
        book_rows = books[book]
        sections = group_by_section(book_rows)
        book_items.append(
            f"""
            <li>
              <a href="{book_page_name(book)}">Book {html.escape(book)}</a>
              <span>{len(sections)} sections, {len(book_rows)} passages, {sum(row["greek_word_count"] for row in book_rows)} Greek words</span>
              <small>{html.escape(ref_range(book_rows))}</small>
            </li>
            """
        )

    passages_body = f"""
    <section>
      <h2>Books</h2>
      <p class="note">Choose a book, then a section. Full passage text is loaded only on section pages.</p>
      <ol class="book-list">
        {"".join(book_items)}
      </ol>
    </section>
    """
    write_text(output_dir / "passages.html", render_page("Eusebius Passages", passages_body))

    all_sections: list[tuple[str, str]] = []
    for book in sorted_books:
        for section in sorted(group_by_section(books[book]), key=numeric_label_sort_key):
            all_sections.append((book, section))

    section_index = {
        (book, section): index for index, (book, section) in enumerate(all_sections)
    }

    for book in sorted_books:
        book_rows = books[book]
        sections = group_by_section(book_rows)
        section_rows = []
        for section in sorted(sections, key=numeric_label_sort_key):
            rows_for_section = sections[section]
            section_rows.append(
                f"""
                <tr>
                  <td><a href="{section_page_name(book, section)}">{html.escape(section_label(section))}</a></td>
                  <td>{len(rows_for_section)}</td>
                  <td>{sum(row["greek_word_count"] for row in rows_for_section)}</td>
                  <td>{html.escape(ref_range(rows_for_section))}</td>
                </tr>
                """
            )
        book_body = f"""
        <p class="breadcrumb"><a href="passages.html">Passages</a> / Book {html.escape(book)}</p>
        <section>
          <h2>Book {html.escape(book)}</h2>
          <table>
            <thead><tr><th>Section</th><th>Passages</th><th>Greek words</th><th>References</th></tr></thead>
            <tbody>{"".join(section_rows)}</tbody>
          </table>
        </section>
        """
        write_text(
            output_dir / book_page_name(book),
            render_page(f"Eusebius Book {book}", book_body),
        )

    for book, section in all_sections:
        section_rows = group_by_section(books[book])[section]
        current_index = section_index[(book, section)]
        previous_link = ""
        next_link = ""
        if current_index > 0:
            previous_book, previous_section = all_sections[current_index - 1]
            previous_link = (
                f'<a href="{section_page_name(previous_book, previous_section)}">'
                f"Previous: Book {html.escape(previous_book)} {html.escape(section_label(previous_section))}</a>"
            )
        if current_index + 1 < len(all_sections):
            next_book, next_section = all_sections[current_index + 1]
            next_link = (
                f'<a href="{section_page_name(next_book, next_section)}">'
                f"Next: Book {html.escape(next_book)} {html.escape(section_label(next_section))}</a>"
            )

        passage_items = []
        for row in section_rows:
            passage_items.append(
                f"""
                <article class="passage" id="p-{html.escape(row["canonical_ref"])}">
                  <h2>{html.escape(row["canonical_ref"])}</h2>
                  <p lang="grc">{html.escape(row["greek_text"])}</p>
                  {render_translation_block(row)}
                </article>
                """
            )
        section_body = f"""
        <p class="breadcrumb">
          <a href="passages.html">Passages</a> /
          <a href="{book_page_name(book)}">Book {html.escape(book)}</a> /
          {html.escape(section_label(section))}
        </p>
        <nav class="pager">{previous_link}{next_link}</nav>
        {"".join(passage_items)}
        <nav class="pager">{previous_link}{next_link}</nav>
        """
        write_text(
            output_dir / section_page_name(book, section),
            render_page(
                f"Eusebius Book {book}, {section_label(section)}",
                section_body,
            ),
        )


def comic_public_relative_path(public_path: str) -> Path:
    """Return a safe site-relative path for a stored comic public path."""
    if not public_path.startswith("/comic/"):
        raise ValueError(f"Comic public path must start with /comic/: {public_path}")
    relative_path = Path(public_path.removeprefix("/"))
    if ".." in relative_path.parts:
        raise ValueError(f"Comic public path may not contain '..': {public_path}")
    return relative_path


def publish_comic_images(
    output_dir: Path,
    comic_rows: list[dict],
    comic_web_dir: Path,
) -> list[dict]:
    """Copy available derivatives into the static tree and return published rows."""
    published_rows = []
    for row in comic_rows:
        relative_path = comic_public_relative_path(row["public_path"])
        suffix = relative_path.suffix
        source_path = (
            comic_web_dir
            / str(row["comic_plan_id"])
            / f'{row["panel_number"]}{suffix}'
        )
        if not source_path.is_file():
            print(
                f"Skipping comic panel with missing derivative: {source_path}",
                file=sys.stderr,
            )
            continue
        target_path = output_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        # Private staging files may be 0600; the deployed web server must read them.
        target_path.chmod(0o644)
        published_rows.append(row)
    return published_rows


def render_comic_viewer(output_dir: Path, comic_rows: list[dict]) -> None:
    """Write a source-linked viewer for rendered documentary-comic panels."""
    if not comic_rows:
        body = """
        <section>
          <h2>No rendered panels published yet</h2>
          <p class="note">Panels will appear here after rendering and static-site publication.</p>
        </section>
        """
        write_text(output_dir / "comics.html", render_page("Eusebius Documentary Comic", body))
        return

    plans: defaultdict[int, list[dict]] = defaultdict(list)
    for row in comic_rows:
        plans[row["comic_plan_id"]].append(row)

    plan_sections = []
    for plan_id, panels in plans.items():
        first = panels[0]
        source_href = (
            f'{section_page_name(first["book"], first["chapter"])}'
            f'#p-{first["canonical_ref"]}'
        )
        translation_note = "First1K English reference"
        if first["translation_model"]:
            translation_note = f'AI English text, {first["translation_model"]}'
        panel_figures = []
        for panel in panels:
            panel_figures.append(
                f"""
                <figure class="comic-panel">
                  <img src="{html.escape(panel["public_path"].removeprefix("/"))}"
                       alt="{html.escape(panel["panel_title"])}" loading="lazy">
                  <figcaption>
                    <h3>Panel {panel["panel_number"]}: {html.escape(panel["panel_title"])}</h3>
                    <p>{html.escape(panel["caption"])}</p>
                    <small>Image: {html.escape(panel["image_model"])}</small>
                  </figcaption>
                </figure>
                """
            )
        plan_sections.append(
            f"""
            <section class="comic-plan" id="plan-{plan_id}">
              <h2>{html.escape(first["plan_title"])}</h2>
              <p>{html.escape(first["plan_summary"])}</p>
              <p class="source-ref">Source: <a href="{html.escape(source_href)}">Eusebius {html.escape(first["canonical_ref"])}</a></p>
              <details>
                <summary>{html.escape(translation_note)}</summary>
                <p>{html.escape(first["english_text"])}</p>
              </details>
              <div class="comic-grid">{"".join(panel_figures)}</div>
            </section>
            """
        )

    body = f"""
    <p class="note">A source-grounded visual edition generated from stored panel plans. Captions and source text remain outside the artwork.</p>
    {"".join(plan_sections)}
    """
    write_text(output_dir / "comics.html", render_page("Eusebius Documentary Comic", body))


def generate(
    output_dir: Path,
    rows: list[dict],
    source: dict,
    comic_rows: list[dict] | None = None,
    comic_web_dir: Path | None = None,
) -> None:
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
    translated_count = sum(1 for row in rows if row["ai_english_translation"])

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
        <dt>Clean English texts</dt><dd>{translated_count}</dd>
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

    render_passage_browser(output_dir, rows)
    published_comic_rows = publish_comic_images(
        output_dir,
        comic_rows or [],
        comic_web_dir or Path("/home/eusebius/eusebius-comic/web"),
    )
    render_comic_viewer(output_dir, published_comic_rows)

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
.book-list { list-style: none; margin: 0; padding: 0; }
.book-list li {
  border-top: 1px solid #d7d2c8;
  display: grid;
  gap: .15rem;
  padding: .85rem 0;
}
.book-list a { font-weight: 700; }
.book-list span, .book-list small, .breadcrumb { color: #5a646d; }
.pager {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin: .8rem 0 1.2rem;
}
.pager a { color: #285680; }
.passage p[lang="grc"] { font-size: 1.08rem; }
.translation-meta { color: #5a646d; font-size: .92rem; margin-bottom: -.25rem; }
details { background: #fff; border: 1px solid #d7d2c8; padding: .65rem .8rem; }
summary { cursor: pointer; font-weight: 700; }
.note { color: #5a646d; }
.source-ref { font-weight: 700; }
.comic-grid { display: grid; gap: 1.5rem; margin-top: 1.2rem; }
.comic-panel { margin: 0; background: white; border: 1px solid #d7d2c8; }
.comic-panel img { display: block; height: auto; width: 100%; }
.comic-panel figcaption { padding: .8rem 1rem; }
.comic-panel h3 { margin: 0 0 .35rem; }
.comic-panel figcaption p { margin: 0 0 .35rem; }
@media (max-width: 680px) {
  dl { grid-template-columns: 1fr; }
  .terms { columns: 1; }
  .pager { display: grid; }
}
""".strip()
        + "\n",
    )


def main() -> None:
    args = parse_args()
    with psycopg.connect(args.database_url) as conn:
        rows = fetch_rows(conn)
        source = fetch_source(conn)
        comic_rows = fetch_comic_rows(conn)
    generate(
        Path(args.output_dir),
        rows,
        source,
        comic_rows,
        Path(args.comic_web_dir),
    )
    print(f"Generated {args.output_dir} with {len(rows)} passages")


if __name__ == "__main__":
    main()
