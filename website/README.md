# Website Generation Module

This directory contains modularized code for the Eusebius website generation.

Original monolithic script has been split into specialized modules:
- `data.py`: Database operations and data retrieval
- `structure.py`: Website directory and structure creation
- `highlighting.py`: Text highlighting and predictor mapping
- `generators.py`: HTML page generators
- `main.py`: Entry point and main execution logic

## Usage
```python
# From the parent directory
python -m website.main --database eusebius.sqlite --output-dir eusebius_site
```