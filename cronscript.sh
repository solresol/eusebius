#!/bin/sh

cd $(dirname $0)

uv run mythic_sceptic_analyser.py --stop 50
uv run extract_proper_nouns.py --stop 50
uv run translate_eusebius.py --stop 50
uv run find_predictors.py
uv run analyse_noun_network.py 
uv run create_website.py
rsync -avz eusebius_site/ merah:/var/www/vhosts/eusebius.symmachus.org/htdocs/
