#!/usr/bin/env python

import sqlite3
import sys
import re
import os.path

def create_db_schema(conn):
    """Create the database schema if it doesn't exist."""
    conn.execute('''
    CREATE TABLE IF NOT EXISTS passages (
        id TEXT PRIMARY KEY,
        passage TEXT NOT NULL
    )
    ''')
    conn.commit()

def parse_eusebius_file(file_path):
    """Parse the Eusebius file and extract sections with their IDs."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Pattern to match section markers and content
        pattern = r'#(\d+\.\d+\.\d+)#\s*(.*?)(?=#\d+\.\d+\.\d+#|$)'
        matches = re.findall(pattern, content, re.DOTALL)
        
        parsed_sections = []
        for section_id, section_text in matches:
            # Clean up the text: remove excessive whitespace and join lines
            cleaned_text = re.sub(r'\s+', ' ', section_text.strip())
            parsed_sections.append((section_id, cleaned_text))
        
        return parsed_sections
    
    except Exception as e:
        raise RuntimeError(f"Failed to parse file {file_path}: {str(e)}")

def import_passages(conn, passages):
    """Import passages into the database."""
    cursor = conn.cursor()
    
    for section_id, passage_text in passages:
        cursor.execute(
            "INSERT OR REPLACE INTO passages (id, passage) VALUES (?, ?)",
            (section_id, passage_text)
        )
    
    conn.commit()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <eusebius_file> [output_db]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_db = sys.argv[2] if len(sys.argv) > 2 else "eusebius.sqlite"
    
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        sys.exit(1)
    
    conn = sqlite3.connect(output_db)
    
    try:
        create_db_schema(conn)
        passages = parse_eusebius_file(input_file)
        
        if not passages:
            print("Warning: No passages found in the input file.")
            sys.exit(0)
        
        import_passages(conn, passages)
        print(f"Successfully imported {len(passages)} passages into {output_db}")
    
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    finally:
        conn.close()
