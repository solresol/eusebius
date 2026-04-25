# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Build and Run Commands
- Run a script: `uv run python script_name.py`
- Run with limited processing when supported: `uv run python script_name.py --stop=N` or `--limit-books=N`
- Run daily analysis: `./cronscript.sh`
- Import First1KGreek into PostgreSQL: `uv run python scripts/import_first1k.py`
- Generate the static site without deploying: `uv run python scripts/generate_site.py`

## Code Style Guidelines
- Use snake_case for function and variable names
- Keep functions focused on a single task with descriptive names
- Place standard library imports first, followed by third-party packages
- Use docstrings for function documentation
- Maintain compatibility with Python 3.11+
- Follow existing error handling patterns with explicit error messages

## Dependencies
- Use `uv` for dependency management
- Core dependencies: matplotlib, networkx, numpy, openai, pandas, psycopg, scikit-learn, tqdm

## Project Structure
- Data flow: fetch TEI → import to PostgreSQL on `raksasa` → analyze/translate/plan → generate website → deploy static output to `merah`
- Database: PostgreSQL (`eusebius` on `raksasa`) is canonical
- Static output: `eusebius_site/`
- Bulk generated comic images should not be committed to Git; store originals under `/home/eusebius/eusebius-comic/` on `raksasa`

## Testing
- Add tests in a "tests" directory if implementing new features
- Test with limited data using the `--stop`, `--stop-after`, or `--limit-books` parameter where available
