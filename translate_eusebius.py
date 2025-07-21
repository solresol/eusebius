#!/usr/bin/env python

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime

from openai import OpenAI
from tqdm import tqdm

def parse_arguments():
    parser = argparse.ArgumentParser(description="Translate Eusebius passages from Greek to English using OpenAI API")
    parser.add_argument("--database", default="eusebius.sqlite", 
                        help="SQLite database file (default: eusebius.sqlite)")
    parser.add_argument("--openai-api-key-file", default="~/.openai.key",
                        help="File containing OpenAI API key (default: ~/.openai.key)")
    parser.add_argument("--stop-after", type=int, default=None,
                        help="Maximum number of records to process (default: all)")
    parser.add_argument("--progress-bar", action="store_true", default=False,
                        help="Show progress bar")
    parser.add_argument("--model", default="gpt-4.5-preview",
                        help="OpenAI model to use (default: gpt-4.5-preview)")
    parser.add_argument("--debug", action="store_true", default=False,
                        help="Print the full API response for debugging")
    
    return parser.parse_args()

def load_openai_api_key(key_file):
    key_path = os.path.expanduser(key_file)
    try:
        with open(key_path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"OpenAI API key file not found: {key_file}")

def create_translation_tables(conn):
    """Create tables for storing translations and tracking processed passages."""
    # Table for storing translations
    conn.execute('''
    CREATE TABLE IF NOT EXISTS translations (
        passage_id TEXT PRIMARY KEY,
        greek_text TEXT NOT NULL,
        english_translation TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        FOREIGN KEY (passage_id) REFERENCES passages(id)
    )
    ''')
    
    conn.commit()

def get_untranslated_passages(conn, limit=None):
    """Get passages that haven't been translated yet."""
    cursor = conn.cursor()
    query = """
    SELECT p.id, p.passage 
    FROM passages p
    LEFT JOIN translations t ON p.id = t.passage_id
    WHERE t.passage_id IS NULL
    ORDER BY p.id
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query)
    return cursor.fetchall()

def save_translation(conn, passage_id, greek_text, english_translation, model, input_tokens, output_tokens):
    """Save translation to the database."""
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO translations (passage_id, greek_text, english_translation, timestamp, model, input_tokens, output_tokens)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (passage_id, greek_text, english_translation, timestamp, model, input_tokens, output_tokens)
    )
    conn.commit()

def translate_passage(client, model, passage_id, passage_text, debug=False):
    """Translate a passage from Greek to English using OpenAI API and track token usage."""
    
    system_prompt = """You are an expert in Ancient Greek who specializes in translating Eusebius. 
Translate the provided Greek passage into clear, accurate English that preserves the meaning and style of the original.
Provide only the translation itself, with no additional notes or commentary.
Your translation should be scholarly but readable, suitable for academic study of Eusebius."""
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Passage {passage_id}:\n\n{passage_text}\n\nPlease translate this passage from Eusebius into English."}
            ]
        )
        
        # Extract token usage
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        
        # Debug output
        if debug:
            print("\n=== DEBUG: FULL API RESPONSE ===")
            print(f"Response object: {response}")
            print("=== END DEBUG ===\n")
        
        # Get the translation directly from the content
        translation = response.choices[0].message.content
        
        return translation.strip(), input_tokens, output_tokens
        
    except Exception as e:
        print(f"Error translating passage {passage_id}: {str(e)}")
        return "", 0, 0

if __name__ == '__main__':
    args = parse_arguments()
    
    # Load OpenAI API key
    api_key = load_openai_api_key(args.openai_api_key_file)
    
    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)
    
    # Connect to the database
    conn = sqlite3.connect(args.database)
    
    try:
        # Create the translation table if it doesn't exist
        create_translation_tables(conn)
        
        # Get untranslated passages
        passages = get_untranslated_passages(conn, args.stop_after)
        
        if not passages:
            print("No untranslated passages found in the database.")
            sys.exit(0)
        
        print(f"Found {len(passages)} untranslated passages.")
        
        # Process passages
        iterator = tqdm(passages) if args.progress_bar else passages
        total_input_tokens = 0
        total_output_tokens = 0
        
        for passage_id, passage_text in iterator:
            translation, input_tokens, output_tokens = translate_passage(
                client, args.model, passage_id, passage_text, args.debug
            )
            
            # Track tokens
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            
            # Save translation to the database
            if translation:
                save_translation(conn, passage_id, passage_text, translation, args.model, input_tokens, output_tokens)
                
                if not args.progress_bar:
                    print(f"Processed passage {passage_id}, tokens={input_tokens}/{output_tokens}")
                    print(f"  Original: {passage_text[:100]}...")
                    print(f"  Translation: {translation[:100]}...")
            else:
                print(f"Failed to translate passage {passage_id}")
            
            # Add a small delay to avoid rate limits
            time.sleep(0.5)
        
        print(f"Translation complete. Total tokens used: {total_input_tokens} input, {total_output_tokens} output")
    
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
    
    finally:
        conn.close()
