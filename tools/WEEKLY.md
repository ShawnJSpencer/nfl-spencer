# Weekly game-story update

Runs every Tuesday morning so the past week's games get their Game Story (story, MVP, big plays).

1. `git pull --ff-only` in the repo.
2. Run `tools/update_current.sh 2026` (needs python3 + pandas; downloads nflverse data from GitHub releases).
3. Check: `data/2026.json` is valid JSON and its count of played games went up (or stayed the same in a bye/off week).
   Print two or three of the newest stories and make sure they read sensibly (team names, score, no "None").
4. If only `data/2026.json` / `data/seasons.json` changed, commit them as "Weekly game stories YYYY-MM-DD" and push to main.
   Never change index.html on these runs.
5. If nflverse hasn't published new games yet, or nothing changed, don't commit — just report that.
