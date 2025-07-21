#!/usr/bin/env python

"""
Entry point for website generation.
This script uses the refactored modules from the website package.
"""

import argparse
import sys
import os
from website.main import main as website_main

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

if __name__ == '__main__':
    # This script simply delegates to the refactored website module
    website_main()
