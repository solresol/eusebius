#!/usr/bin/env python
"""Import Eusebius' Historia Ecclesiastica from First1KGreek into PostgreSQL."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg


GREEK_URL = (
    "https://raw.githubusercontent.com/OpenGreekAndLatin/First1KGreek/master/"
    "data/tlg2018/tlg002/tlg2018.tlg002.1st1K-grc1.xml"
)
ENGLISH_URL = (
    "https://raw.githubusercontent.com/OpenGreekAndLatin/First1KGreek/master/"
    "data/tlg2018/tlg002/tlg2018.tlg002.1st1K-eng1.xml"
)
WORK_CTS_URN = "urn:cts:greekLit:tlg2018.tlg002"
GREEK_EDITION_URN = "urn:cts:greekLit:tlg2018.tlg002.1st1K-grc1"
SOURCE_ID = "first1k-tlg2018-tlg002-grc1"
WORK_ID = "historia-ecclesiastica"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


@dataclass(frozen=True)
class Passage:
    canonical_ref: str
    book: str
    chapter: str
    paragraph_index: int
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("EUSEBIUS_DATABASE_URL", "postgresql:///eusebius"),
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Directory for cached upstream XML files",
    )
    parser.add_argument(
        "--limit-books",
        type=int,
        default=None,
        help="Only import the first N books; useful for smoke tests",
    )
    return parser.parse_args()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def word_count(value: str) -> int:
    return len(re.findall(r"\w+", value, flags=re.UNICODE))


def fetch(url: str, raw_dir: Path) -> tuple[Path, bytes, str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1]
    path = raw_dir / filename
    with urllib.request.urlopen(url, timeout=60) as response:
        content = response.read()
    path.write_bytes(content)
    return path, content, hashlib.sha256(content).hexdigest()


def direct_child_text(element: ET.Element) -> str:
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in list(element):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag not in {"note", "pb"}:
            parts.append("".join(child.itertext()))
        if child.tail:
            parts.append(child.tail)
    return clean_text(" ".join(parts))


def parse_passages(xml_bytes: bytes, *, limit_books: int | None = None) -> list[Passage]:
    root = ET.fromstring(xml_bytes)
    body = root.find(".//tei:body", NS)
    if body is None:
        raise RuntimeError("No TEI body found")

    passages: list[Passage] = []
    books = body.findall(".//tei:div[@subtype='book']", NS)
    if limit_books is not None:
        books = books[:limit_books]

    for book in books:
        book_n = book.get("n") or "unknown"
        for chapter in book.findall("./tei:div[@subtype='chapter']", NS):
            chapter_n = chapter.get("n") or "unknown"
            if chapter_n == "toc":
                continue
            paragraph_index = 0
            for paragraph in chapter.findall("./tei:p", NS):
                text = direct_child_text(paragraph)
                if not text:
                    continue
                paragraph_index += 1
                canonical_ref = f"{book_n}.{chapter_n}.{paragraph_index}"
                passages.append(
                    Passage(
                        canonical_ref=canonical_ref,
                        book=book_n,
                        chapter=chapter_n,
                        paragraph_index=paragraph_index,
                        text=text,
                    )
                )
    return passages


def load_schema(conn: psycopg.Connection) -> None:
    schema_path = Path(__file__).with_name("init_db.sql")
    conn.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def import_passages(
    conn: psycopg.Connection,
    *,
    greek_xml: bytes,
    greek_sha256: str,
    english_xml: bytes,
    fetched_at: datetime,
    limit_books: int | None,
) -> int:
    greek_passages = parse_passages(greek_xml, limit_books=limit_books)
    english_by_ref = {
        passage.canonical_ref: passage.text
        for passage in parse_passages(english_xml, limit_books=limit_books)
    }

    with conn.transaction():
        conn.execute(
            """
            INSERT INTO sources (
                source_id, title, source_url, cts_urn, edition_note,
                license_note, raw_sha256, raw_bytes, fetched_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id) DO UPDATE SET
                source_url = EXCLUDED.source_url,
                raw_sha256 = EXCLUDED.raw_sha256,
                raw_bytes = EXCLUDED.raw_bytes,
                fetched_at = EXCLUDED.fetched_at
            """,
            (
                SOURCE_ID,
                "Historia Ecclesiastica",
                GREEK_URL,
                GREEK_EDITION_URN,
                "First1KGreek TEI edition, Greek text with matching English translation file",
                "OpenGreekAndLatin First1KGreek repository; GitHub lists CC BY-SA 4.0",
                greek_sha256,
                len(greek_xml),
                fetched_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO works (work_id, title, author, cts_urn, source_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (work_id) DO UPDATE SET
                title = EXCLUDED.title,
                author = EXCLUDED.author,
                cts_urn = EXCLUDED.cts_urn,
                source_id = EXCLUDED.source_id
            """,
            (
                WORK_ID,
                "Historia Ecclesiastica",
                "Eusebius of Caesarea",
                WORK_CTS_URN,
                SOURCE_ID,
            ),
        )
        for passage in greek_passages:
            english_text = english_by_ref.get(passage.canonical_ref, "")
            conn.execute(
                """
                INSERT INTO passages (
                    work_id, canonical_ref, book, chapter, paragraph_index,
                    greek_text, english_text, greek_word_count, english_word_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (canonical_ref) DO UPDATE SET
                    greek_text = EXCLUDED.greek_text,
                    english_text = EXCLUDED.english_text,
                    greek_word_count = EXCLUDED.greek_word_count,
                    english_word_count = EXCLUDED.english_word_count,
                    imported_at = now()
                """,
                (
                    WORK_ID,
                    passage.canonical_ref,
                    passage.book,
                    passage.chapter,
                    passage.paragraph_index,
                    passage.text,
                    english_text or None,
                    word_count(passage.text),
                    word_count(english_text),
                ),
            )
    return len(greek_passages)


def main() -> None:
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    fetched_at = datetime.now(UTC)

    greek_path, greek_xml, greek_sha256 = fetch(GREEK_URL, raw_dir)
    english_path, english_xml, _english_sha256 = fetch(ENGLISH_URL, raw_dir)

    with psycopg.connect(args.database_url) as conn:
        load_schema(conn)
        count = import_passages(
            conn,
            greek_xml=greek_xml,
            greek_sha256=greek_sha256,
            english_xml=english_xml,
            fetched_at=fetched_at,
            limit_books=args.limit_books,
        )

    print(f"Imported {count} passages into PostgreSQL")
    print(f"Cached Greek XML: {greek_path}")
    print(f"Cached English XML: {english_path}")


if __name__ == "__main__":
    main()
