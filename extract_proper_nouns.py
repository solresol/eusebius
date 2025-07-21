#!/usr/bin/env python

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

from openai import OpenAI
from tqdm import tqdm

def parse_arguments():
    parser = argparse.ArgumentParser(description="Extract proper nouns from Eusebius passages using OpenAI API")
    parser.add_argument("--database", default="eusebius.sqlite", 
                        help="SQLite database file (default: eusebius.sqlite)")
    parser.add_argument("--openai-api-key-file", default="~/.openai.key",
                        help="File containing OpenAI API key (default: ~/.openai.key)")
    parser.add_argument("--stop-after", type=int, default=None,
                        help="Maximum number of records to process (default: all)")
    parser.add_argument("--progress-bar", action="store_true", default=False,
                        help="Show progress bar")
    parser.add_argument("--model", default="gpt-4.1",
                        help="OpenAI model to use (default: gpt-4.1)")
    parser.add_argument("--debug", action="store_true", default=False,
                        help="Print the full API response for debugging")
    
    return parser.parse_args()

def load_openai_api_key(key_file):
    key_path = os.path.expanduser(key_file)
    with open(key_path, 'r') as f:
        return f.read().strip()

def create_noun_tables(conn):
    """Create tables for storing proper nouns and tracking processed passages."""
    # Table for storing proper nouns with enhanced schema
    conn.execute('''
    CREATE TABLE IF NOT EXISTS proper_nouns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        passage_id TEXT NOT NULL,
        exact_form TEXT NOT NULL,
        reference_form TEXT NOT NULL,
        english_transcription TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        FOREIGN KEY (passage_id) REFERENCES passages(id),
        UNIQUE(passage_id, exact_form)
    )
    ''')
    
    # Table for tracking processed passages
    conn.execute('''
    CREATE TABLE IF NOT EXISTS noun_extraction_status (
        passage_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        is_processed BOOLEAN NOT NULL DEFAULT 1,
        FOREIGN KEY (passage_id) REFERENCES passages(id)
    )
    ''')
    
    conn.commit()

def get_unprocessed_passages(conn, limit=None):
    """Get passages that haven't been processed for noun extraction yet."""
    cursor = conn.cursor()
    query = """
    SELECT p.id, p.passage 
    FROM passages p
    LEFT JOIN noun_extraction_status n ON p.id = n.passage_id
    WHERE n.passage_id IS NULL
    ORDER BY p.id
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query)
    return cursor.fetchall()

def save_proper_nouns(conn, passage_id, noun_list):
    """Save proper nouns to the database."""
    if not noun_list:
        return
    
    cursor = conn.cursor()
    
    # Insert each proper noun with enhanced data
    for noun_entry in noun_list:
        exact_form = noun_entry.get("as_appears_in_passage")
        reference_form = noun_entry.get("canonical_form")
        english_transcription = noun_entry.get("english_transcription")
        entity_type = noun_entry.get("entity_type")
        
        if exact_form and reference_form and english_transcription and entity_type:
            cursor.execute(
                """
                INSERT OR IGNORE INTO proper_nouns 
                (passage_id, exact_form, reference_form, english_transcription, entity_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (passage_id, exact_form, reference_form, english_transcription, entity_type)
            )
    
    conn.commit()

def mark_passage_processed(conn, passage_id, model, input_tokens, output_tokens):
    """Mark a passage as processed and save token usage data."""
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO noun_extraction_status (passage_id, timestamp, model, input_tokens, output_tokens)
        VALUES (?, ?, ?, ?, ?)
        """,
        (passage_id, timestamp, model, input_tokens, output_tokens)
    )
    conn.commit()

def extract_proper_nouns(client, model, passage_id, passage_text, debug=False):
    """Extract proper nouns using OpenAI API with tool calls and track token usage."""
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "save_proper_nouns",
                "description": "Save the proper nouns extracted from the passage",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "proper_nouns": {
                            "type": "array",
                            "description": "List of proper nouns found in the passage",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "as_appears_in_passage": {
                                        "type": "string",
                                        "description": "The exact form of the proper noun as it appears in the passage (preserve case and inflection)"
                                    },
                                    "canonical_form": {
                                        "type": "string",
                                        "description": "The canonical nominative form of the proper noun as it would appear in a reference work"
                                    },
                                    "english_transcription": {
                                        "type": "string",
                                        "description": "English transliteration or transcription of the Greek proper noun"
                                    },
                                    "entity_type": {
                                        "type": "string",
                                        "enum": ["person", "place", "deity", "other"],
                                        "description": "The type of entity this proper noun represents"
                                    }
                                },
                                "required": ["as_appears_in_passage", "canonical_form", "english_transcription", "entity_type"]
                            }
                        }
                    },
                    "required": ["proper_nouns"]
                }
            }
        }
    ]
    
    system_prompt = """Act as a Classical Greek scholar specializing in Eusebius. Extract all proper nouns (people, places, deities) from the given passage. For each proper noun, provide:
1. The exact form as it appears in the passage (preserve case and inflection)
2. The canonical nominative form you would use in a reference work or index
3. An English transcription/transliteration of the name
4. The entity type (person, place, deity, or other)

Return a list of objects, where each object contains:
- "as_appears_in_passage": the exact form as it appears in the text
- "canonical_form": the canonical nominative form
- "english_transcription": how the name would be written in English (e.g., "Athens" for "Ἀθῆναι")
- "entity_type": one of "person", "place", "deity", or "other"

For example, if "Ἀθηνᾶς" appears in the text, you would include:
{
  "as_appears_in_passage": "Ἀθηνᾶς",
  "canonical_form": "Ἀθηνᾶ",
  "english_transcription": "Athena",
  "entity_type": "deity"
}

If no proper nouns are found (which is unlikely in Eusebius), return an empty list.

IMPORTANT: Almost every passage from Eusebius mentions at least one place or person. Look carefully for proper nouns including place names, personal names, names of gods, heroes, and locations. Greek proper nouns often begin with capital letters."""
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Passage {passage_id}:\n\n{passage_text}\n\nExtract all proper nouns from this passage with their English transcriptions and entity types."}
            ],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "save_proper_nouns"}}
        )
        
        # Extract token usage
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        
        # Debug output
        if debug:
            print("\n=== DEBUG: FULL API RESPONSE ===")
            print(f"Response object: {response}")
            print("=== END DEBUG ===\n")
        
        tool_calls = response.choices[0].message.tool_calls
        if tool_calls and len(tool_calls) > 0:
            function_call = tool_calls[0]
            try:
                function_args = json.loads(function_call.function.arguments)
                if debug:
                    print(f"Function arguments: {function_args}")
                proper_nouns = function_args.get('proper_nouns', [])
                # Ensure we have a list, not None
                if proper_nouns is None:
                    proper_nouns = []
                return proper_nouns, input_tokens, output_tokens
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON from function arguments: {e}")
                if debug:
                    print(f"Raw function arguments: {function_call.function.arguments}")
                return [], input_tokens, output_tokens
        else:
            print(f"No tool calls found for passage {passage_id}")
            return [], input_tokens, output_tokens
        
    except Exception as e:
        print(f"Error extracting proper nouns from passage {passage_id}: {str(e)}")
        return [], 0, 0

if __name__ == '__main__':
    args = parse_arguments()
    
    # Load OpenAI API key
    api_key = load_openai_api_key(args.openai_api_key_file)
    
    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)
    
    # Connect to the database
    conn = sqlite3.connect(args.database)
    
    try:
        # Create the tables if they don't exist
        create_noun_tables(conn)
        
        # Get unprocessed passages
        passages = get_unprocessed_passages(conn, args.stop_after)
        
        if not passages:
            print("No unprocessed passages found in the database.")
            sys.exit(0)
        
        print(f"Found {len(passages)} unprocessed passages.")
        
        # Process passages
        iterator = tqdm(passages) if args.progress_bar else passages
        total_input_tokens = 0
        total_output_tokens = 0
        
        for passage_id, passage_text in iterator:
            proper_nouns, input_tokens, output_tokens = extract_proper_nouns(
                client, args.model, passage_id, passage_text, args.debug
            )
            
            # Track tokens
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            
            # Save proper nouns to the database
            if proper_nouns:
                save_proper_nouns(conn, passage_id, proper_nouns)
                
                if not args.progress_bar:
                    print(f"Processed passage {passage_id}: found {len(proper_nouns)} proper nouns, tokens={input_tokens}/{output_tokens}")
                    for noun in proper_nouns:
                        print(f"  - {noun.get('as_appears_in_passage')} → {noun.get('canonical_form')} ({noun.get('english_transcription')}, {noun.get('entity_type')})")
            else:
                if not args.progress_bar:
                    print(f"Processed passage {passage_id}: no proper nouns found, tokens={input_tokens}/{output_tokens}")
            
            # Mark passage as processed
            mark_passage_processed(conn, passage_id, args.model, input_tokens, output_tokens)
            
            # Add a small delay to avoid rate limits
            time.sleep(0.5)
        
        print(f"Processing complete. Total tokens used: {total_input_tokens} input, {total_output_tokens} output")
    
    except Exception as e:
        # Let the exception propagate to get the stack trace as per your preference
        raise e
    
    finally:
        conn.close()
