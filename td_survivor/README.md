# TD Survivor planner

Picks for the Swolecast $10K TD Survivor (Splash). Each week, every entry picks one
player who has to score a rushing, receiving or return TD (passing TDs don't count),
and a player can't be used twice. The alternate only plays if the primary is inactive.

## How it works

1. **Opportunity model** (`survivor.py`): from 2026 nflverse play-by-play, it measures
   the league TD rate for each carry/target by yards-to-goal (1-2, 3-5, 6-10, 11-20, 21+).
   Each player's expected TDs (xTD) are blended 65/35 with actual TDs, weighted toward
   recent weeks, and turned into a **share of his team's TDs**.
2. **Game environment**: implied team points from the Vegas spread/total where posted
   (Weeks 8-9). Later weeks use regressed points-for/points-against ratings. Byes are 0.
   `P(TD) = 1 - exp(-share x implied_pts x TDs_per_point)`.
3. **Market blend**: where sportsbook anytime-TD prices exist (`config.json`), they are
   de-vigged and blended 50/50. Injury multipliers are applied.
4. **Path optimizer**: for each entry, a Hungarian assignment over players x remaining
   weeks maximizes discounted sum of log P(survive). This saves elite matchups for the
   week they're elite (e.g. Kenneth Walker vs NYJ in Week 9).
5. **Joint pick**: the two entries' current-week picks are chosen together, adding
   log P(at least one entry survives), so the two entries don't die on the same player.

## Weekly use

```bash
pip install pandas numpy scipy
# edit config.json: current_week, add last week's picks to each entry's "used",
# paste new anytime-TD odds under market_odds, update injuries
python td_survivor/survivor.py --refresh
```

Output: `output/weekNN_plan.md` (picks, board, full-season paths) and
`output/weekNN_probabilities.csv` (every player x week).
