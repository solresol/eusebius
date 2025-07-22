#!/bin/sh

cd $(dirname $0)

uv run extract_proper_nouns.py --stop 50
uv run translate_eusebius.py --stop 50
uv run create_website.py
rsync -avz eusebius_site/ merah:/var/www/vhosts/eusebius.symmachus.org/htdocs/
