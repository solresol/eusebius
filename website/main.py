#!/usr/bin/env python

"""Main entry point for website generation."""

import argparse
import sqlite3
import sys
import os
from datetime import datetime

from .data import (
    get_analyzed_passages,
    get_mythicness_predictors,
    get_skepticism_predictors,
    get_proper_nouns_by_passage
)
from .structure import create_website_structure
from .highlighting import create_predictor_maps
from .generators import (
    generate_home_page,
    generate_mythic_page,
    generate_skepticism_page,
    generate_mythic_words_page,
    generate_skeptic_words_page
)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Create a static website to visualize mythic and skeptical aspects of Eusebius passages")
    parser.add_argument("--database", default="eusebius.sqlite", 
                        help="SQLite database file (default: eusebius.sqlite)")
    parser.add_argument("--output-dir", default="eusebius_site",
                        help="Output directory for the static website (default: eusebius_site)")
    parser.add_argument("--max-passages", type=int, default=None,
                        help="Maximum number of passages to include (default: all)")
    parser.add_argument("--title", default="Eusebius Analysis",
                        help="Title for the website (default: 'Eusebius Analysis')")
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    
    # Connect to the database
    conn = sqlite3.connect(args.database)
    
    try:
        # Get data from database
        passages_df = get_analyzed_passages(conn, args.max_passages)
        mythic_predictors = get_mythicness_predictors(conn)
        skeptic_predictors = get_skepticism_predictors(conn)
        proper_nouns_dict = get_proper_nouns_by_passage(conn)
        
        if len(passages_df) == 0:
            print("No analyzed passages found in the database.")
            sys.exit(0)
        
        if len(mythic_predictors) == 0 or len(skeptic_predictors) == 0:
            print("No predictor data found in the database. Run the analysis program first.")
            sys.exit(1)
        
        print(f"Found {len(passages_df)} analyzed passages.")
        print(f"Found {len(mythic_predictors)} mythicness predictors.")
        print(f"Found {len(skeptic_predictors)} skepticism predictors.")
        
        # Create website structure
        output_dir, css_dir = create_website_structure(args.output_dir)
        
        # Create color and class maps for highlighting
        mythic_color_map, skeptic_color_map, mythic_class_map, skeptic_class_map = create_predictor_maps(
            mythic_predictors, skeptic_predictors
        )
        
        # Get timestamp for the website
        timestamp = datetime.now().strftime("%Y-%m-%d at %H:%M:%S")
        
        # Generate all pages
        generate_home_page(output_dir, args.title, timestamp)
        generate_mythic_page(passages_df, mythic_color_map, mythic_class_map, proper_nouns_dict, output_dir, args.title)
        generate_skepticism_page(passages_df, skeptic_color_map, skeptic_class_map, proper_nouns_dict, output_dir, args.title)
        generate_mythic_words_page(mythic_predictors, output_dir, args.title)
        generate_skeptic_words_page(skeptic_predictors, output_dir, args.title)
        
        print(f"Website generated successfully in '{output_dir}'")
        print(f"Open '{os.path.join(output_dir, 'index.html')}' in a web browser to view it.")
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
    
    finally:
        conn.close()
        
if __name__ == '__main__':
    import os
    main()
