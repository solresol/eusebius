#!/usr/bin/env python
"""Simple website generator producing a D3 network page."""
import argparse
import os
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a static site with the Eusebius network visualisation"
    )
    parser.add_argument(
        "--database", default="eusebius.sqlite", help="SQLite database file"
    )
    parser.add_argument(
        "--output-dir", default="eusebius_site", help="Directory for the website"
    )
    parser.add_argument(
        "--min-cooccurrence",
        type=int,
        default=1,
        help="Minimum links for network edges",
    )
    parser.add_argument(
        "--top-nodes",
        type=int,
        default=100,
        help="Number of nodes to highlight in visualisations",
    )
    args = parser.parse_args()

    network_dir = os.path.join(args.output_dir, "network_viz")
    os.makedirs(network_dir, exist_ok=True)

    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "analyse_noun_network.py"),
        "--database",
        args.database,
        "--output-dir",
        network_dir,
        "--min-cooccurrence",
        str(args.min_cooccurrence),
        "--top-nodes",
        str(args.top_nodes),
    ]
    subprocess.run(cmd, check=True)

    index_html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\">
    <title>Eusebius Network</title>
</head>
<body>
    <h1>Eusebius Network Visualisation</h1>
    <p><a href=\"network_viz/index.html\">View network graph</a></p>
</body>
</html>
"""
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)


if __name__ == "__main__":
    main()
