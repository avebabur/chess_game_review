# Golden explanation set

Hand-curated positions with what a good explanation MUST say (and must not).
`scripts/golden_check.py` runs the live explanation pipeline over every entry
and scores it — run it after ANY change to the explanation engine.

## How to add a position

Append a block to `positions.txt` (blocks separated by a blank line):

```
fen: 6r1/1p6/4k3/P3nRK1/6P1/8/8/8 w - - 5 49
played: Kf4
best: Kh5
mention: Rxg4
avoid: toward the center
note: Kf4 steps off the g-file so Rxg4+ wins the pawn. Kh5 keeps guarding g4.
```

Field meanings:
- `fen` — position BEFORE your move (copy from the app or lichess analysis).
- `played` — the move you played (SAN).
- `best` — the better move if you know it (optional; engine confirms anyway).
- `mention` — words/phrases a good explanation must contain, separated by `|`
  (optional — leave out to just eyeball the output in the report).
- `avoid` — phrases that must NOT appear, separated by `|` (optional).
- `note` — what the ideal explanation would say, in your own words.

Run:

```
venv/bin/python scripts/golden_check.py            # full report
venv/bin/python scripts/golden_check.py --fast     # skip engine, template-only checks
```

`mined_candidates.txt` holds positions auto-extracted from annotated lichess
studies (`scripts/mine_golden_candidates.py`) — move the good ones into
`positions.txt` and write `mention`/`avoid` for them.
