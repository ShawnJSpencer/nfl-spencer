#!/usr/bin/env bash
# Rebuild one season's game stories (default: the current season) from nflverse data
# and refresh data/seasons.json. Usage: tools/update_current.sh [season]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SEASON="${1:-2026}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$REPO/tools/build_seasons.py" "$WORK/"
mkdir -p "$WORK/pbp"
R=https://github.com/nflverse/nflverse-data/releases/download
curl -sSfL -o "$WORK/games.csv" "$R/schedules/games.csv"
curl -sSfL -o "$WORK/teams_colors_logos.csv" "$R/teams/teams_colors_logos.csv"
curl -sSfL -o "$WORK/players.csv" "$R/players/players.csv"
curl -sSfL -o "$WORK/pbp/play_by_play_$SEASON.csv.gz" "$R/pbp/play_by_play_$SEASON.csv.gz"
python3 "$WORK/build_seasons.py" "$REPO/data" "$SEASON"
python3 - "$REPO/data" <<'PY'
import json, glob, sys, os
d0 = sys.argv[1]; idx = []
for f in sorted(glob.glob(os.path.join(d0, '[0-9]*.json'))):
    d = json.load(open(f)); c = d.get('champ'); t = d['teams'].get(c) if c else None
    idx.append({'s': d['s'], 'c': [c, t[1], t[2], t[4]] if t else None})
json.dump(idx, open(os.path.join(d0, 'seasons.json'), 'w'), separators=(',', ':'))
print('seasons.json:', len(idx), 'seasons')
PY
