#!/usr/bin/env python

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import openai
from openai import OpenAI
from tqdm import tqdm

def parse_arguments():
    parser = argparse.ArgumentParser(description="Analyze Eusebius passages using OpenAI API")
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
    
    return parser.parse_args()

def load_openai_api_key(key_file):
    key_path = os.path.expanduser(key_file)
    try:
        with open(key_path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"OpenAI API key file not found: {key_file}")

def create_tracking_table(conn):
    """Create the table for tracking API calls if it doesn't exist."""
    conn.execute('''
    CREATE TABLE IF NOT EXISTS content_queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        passage_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        FOREIGN KEY (passage_id) REFERENCES passages(id)
    )
    ''')
    conn.commit()

def get_unprocessed_passages(conn, limit=None):
    """Get passages that haven't been analyzed yet."""
    cursor = conn.cursor()
    query = """
    SELECT id, passage 
    FROM passages 
    WHERE references_mythic_era IS NULL 
    ORDER BY id
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query)
    return cursor.fetchall()

def save_analysis_results(conn, passage_id, references_mythic_era, expresses_scepticism):
    """Save analysis results to the database."""
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE passages 
        SET references_mythic_era = ?, expresses_scepticism = ? 
        WHERE id = ?
        """,
        (references_mythic_era, expresses_scepticism, passage_id)
    )
    conn.commit()

def save_query_metadata(conn, passage_id, model, input_tokens, output_tokens):
    """Save API call metadata to the tracking table."""
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO content_queries (passage_id, timestamp, model, input_tokens, output_tokens)
        VALUES (?, ?, ?, ?, ?)
        """,
        (passage_id, timestamp, model, input_tokens, output_tokens)
    )
    conn.commit()

def analyze_passage(client, model, passage_id, passage_text):
    """Analyze a passage using OpenAI API with tool calls and track token usage."""
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "save_annotations",
                "description": "Save the analysis of whether the passage references the mythic era and expresses skepticism",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "references_mythic_era": {
                            "type": "boolean",
                            "description": "Whether the passage references the mythic era (true) or historical era (false)"
                        },
                        "expresses_scepticism": {
                            "type": "boolean",
                            "description": "Whether Eusebius expresses skepticism about the subject matter"
                        }
                    },
                    "required": ["references_mythic_era", "expresses_scepticism"]
                }
            }
        }
    ]
    
    system_prompt = """Act as a Eusebius scholar and report whether this passage of Eusebius is a reference to the mythic era, or whether it is closer to being historical. Then report whether Eusebius shows scepticism about the subject matter he is writing about."""
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Passage {passage_id}:\n\n{passage_text}\n\nAnalyze this passage and provide your results using the save_annotations function."}
            ],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "save_annotations"}}
        )
        
        # Extract token usage
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        
        tool_calls = response.choices[0].message.tool_calls
        if tool_calls:
            function_call = tool_calls[0]
            function_args = json.loads(function_call.function.arguments)
            return (
                function_args.get('references_mythic_era'),
                function_args.get('expresses_scepticism'),
                input_tokens,
                output_tokens
            )
        
        # Return None values if no tool call was made
        return None, None, input_tokens, output_tokens
        
    except Exception as e:
        print(f"Error analyzing passage {passage_id}: {str(e)}")
        return None, None, 0, 0

if __name__ == '__main__':
    args = parse_arguments()
    
    # Load OpenAI API key
    api_key = load_openai_api_key(args.openai_api_key_file)
    
    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)
    
    # Connect to the database
    conn = sqlite3.connect(args.database)
    
    try:
        # Create the tracking table if it doesn't exist
        create_tracking_table(conn)
        
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
            references_mythic_era, expresses_scepticism, input_tokens, output_tokens = analyze_passage(
                client, args.model, passage_id, passage_text
            )
            
            # Track tokens regardless of success
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            
            # Save token usage to the database
            save_query_metadata(conn, passage_id, args.model, input_tokens, output_tokens)
            
            if references_mythic_era is not None and expresses_scepticism is not None:
                save_analysis_results(
                    conn, passage_id, references_mythic_era, expresses_scepticism
                )
                
                if not args.progress_bar:
                    print(f"Processed passage {passage_id}: mythic_era={references_mythic_era}, scepticism={expresses_scepticism}, tokens={input_tokens}/{output_tokens}")
            else:
                print(f"Failed to analyze passage {passage_id}")
            
            # Add a small delay to avoid rate limits
            time.sleep(0.5)
        
        print(f"Processing complete. Total tokens used: {total_input_tokens} input, {total_output_tokens} output")
    
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
    
    finally:
        conn.close()
