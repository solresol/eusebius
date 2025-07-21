# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run Commands
- Run a script: `python script_name.py`
- Run with limited processing: `python script_name.py --stop=N` (process N items)
- Run daily analysis: `./cronscript.sh`

## Code Style Guidelines
- Use snake_case for function and variable names
- Keep functions focused on a single task with descriptive names
- Place standard library imports first, followed by third-party packages
- Use docstrings for function documentation
- Maintain compatibility with Python 3.11+
- Follow existing error handling patterns with explicit error messages

## Dependencies
- Use `uv` for dependency management
- Core dependencies: matplotlib, networkx, numpy, openai, pandas, scikit-learn, tqdm

## Project Structure
- Data flow: import → extract → analyze → visualize → generate website
- Database: SQLite (eusebius.sqlite)
- Network analysis outputs feed into website generation

## Testing
- Add tests in a "tests" directory if implementing new features
- Test with limited data using the --stop parameter