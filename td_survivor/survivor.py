"""TD Survivor planner.

Projects every skill player's chance to score a non-passing TD in each remaining
week, then picks a season-long path for each entry. Each entry's path is a
max-weight assignment (each player used at most once, one pick per week), and
the two entries' Week-N picks are chosen together so they don't share a
single point of failure.

    python td_survivor/survivor.py            # uses config.json, writes output/
    python td_survivor/survivor.py --refresh  # re-download nflverse data
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "output"
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
           "pbp/play_by_play_{season}.csv.gz")
SEASON = 2026

# Yards-to-goal buckets; the TD rate per opportunity in each bucket is
# measured from the current season's play-by-play.
RUSH_BINS = [0, 2, 5, 10, 20, 100]
REC_BINS = [0, 5, 10, 20, 100]
COLS = ["pid", "name", "posteam", "game_id", "week", "xtd", "td", "rz", "gl"]


def load(refresh=False):
    DATA.mkdir(exist_ok=True)
    games_path = DATA / "games.csv"
    pbp_path = DATA / f"play_by_play_{SEASON}.csv.gz"
    if refresh or not games_path.exists():
        pd.read_csv(GAMES_URL).to_csv(games_path, index=False)
    if refresh or not pbp_path.exists():
        import urllib.request
        urllib.request.urlretrieve(PBP_URL.format(season=SEASON), pbp_path)
    games = pd.read_csv(games_path)
    games = games[(games.season == SEASON) & (games.game_type == "REG")]
    pbp = pd.read_csv(pbp_path, low_memory=False)
    pbp = pbp[pbp.season_type == "REG"].copy()
    return games, pbp


def opportunities(pbp):
    """One row per player-game: xTD from opportunity location, actual TDs."""
    live = pbp[(pbp.two_point_attempt != 1)]

    rush = live[live.rusher_player_id.notna() & (live.qb_kneel != 1)].copy()
    rush["bucket"] = pd.cut(rush.yardline_100, RUSH_BINS)
    rush_rate = rush.groupby("bucket", observed=True).rush_touchdown.mean()
    rush["xtd"] = rush.bucket.map(rush_rate).astype(float)
    rush["td"] = rush.rush_touchdown.fillna(0)
    rush["rz"] = (rush.yardline_100 <= 20).astype(int)
    rush["gl"] = (rush.yardline_100 <= 5).astype(int)
    # pbp already has "name"/"id" columns, so select before renaming.
    rush = rush[["rusher_player_id", "rusher_player_name", "posteam", "game_id", "week",
                 "xtd", "td", "rz", "gl"]].set_axis(COLS, axis=1)

    rec = live[live.receiver_player_id.notna()].copy()
    rec["bucket"] = pd.cut(rec.yardline_100, REC_BINS)
    rec_rate = rec.groupby("bucket", observed=True).pass_touchdown.mean()
    rec["xtd"] = rec.bucket.map(rec_rate).astype(float)
    rec["td"] = rec.pass_touchdown.fillna(0)
    rec["rz"] = (rec.yardline_100 <= 20).astype(int)
    rec["gl"] = (rec.yardline_100 <= 5).astype(int)
    rec = rec[["receiver_player_id", "receiver_player_name", "posteam", "game_id", "week",
               "xtd", "td", "rz", "gl"]].set_axis(COLS, axis=1)

    both = pd.concat([rush, rec])
    pg = (both.groupby(["pid", "game_id", "week"])
          .agg(name=("name", "last"), team=("posteam", "last"), xtd=("xtd", "sum"),
               td=("td", "sum"), rz=("rz", "sum"), gl=("gl", "sum"))
          .reset_index())

    # Return / defensive TDs also count; credit actual ones to the scorer.
    other = pbp[(pbp.touchdown == 1) & (pbp.rush_touchdown != 1) & (pbp.pass_touchdown != 1)
                & pbp.td_player_id.notna()]
    extra = other.groupby(["td_player_id", "game_id"]).size().rename("ret_td")
    pg = pg.merge(extra, left_on=["pid", "game_id"], right_index=True, how="left")
    pg["td"] += pg.ret_td.fillna(0)
    return pg.drop(columns="ret_td"), rush_rate, rec_rate


def team_ratings(games, cfg):
    """Points-for / points-against per game, regressed to league average."""
    done = games[games.home_score.notna()]
    rows = []
    for _, g in done.iterrows():
        rows.append((g.home_team, g.home_score, g.away_score))
        rows.append((g.away_team, g.away_score, g.home_score))
    df = pd.DataFrame(rows, columns=["team", "pf", "pa"])
    lg = df.pf.mean()
    k = cfg["model"]["rating_regression_games"]
    agg = df.groupby("team").agg(n=("pf", "size"), pf=("pf", "sum"), pa=("pa", "sum"))
    off = (agg.pf + k * lg) / (agg.n + k)
    dfn = (agg.pa + k * lg) / (agg.n + k)
    return off, dfn, lg


def implied_points(games, off, dfn, lg, cfg):
    """Implied team points for every remaining game: Vegas if posted, else ratings."""
    hfa = cfg["model"]["home_field_pts"]
    out = []
    for _, g in games[games.home_score.isna()].iterrows():
        if pd.notna(g.spread_line) and pd.notna(g.total_line):
            # nflverse spread_line is positive when the home team is favored.
            home = (g.total_line + g.spread_line) / 2
            away = (g.total_line - g.spread_line) / 2
            src = "vegas"
        else:
            home = off[g.home_team] + dfn[g.away_team] - lg + hfa / 2
            away = off[g.away_team] + dfn[g.home_team] - lg - hfa / 2
            src = "ratings"
        out.append((g.week, g.home_team, g.away_team, home, g.gameday, g.gametime, src))
        out.append((g.week, g.away_team, g.home_team, away, g.gameday, g.gametime, src))
    return pd.DataFrame(out, columns=["week", "team", "opp", "pts", "gameday", "gametime", "src"])


def player_shares(pg, pbp, cfg):
    """Each player's recency-weighted share of his team's expected TDs."""
    m = cfg["model"]
    cur = cfg["current_week"]
    team_td = (pbp[(pbp.rush_touchdown == 1) | (pbp.pass_touchdown == 1)]
               .groupby(["game_id", "posteam"]).size().rename("team_td"))
    team_x = pg.groupby(["game_id", "team"]).xtd.sum().rename("team_xtd")
    pg = pg.merge(team_td, left_on=["game_id", "team"], right_index=True, how="left")
    pg = pg.merge(team_x, left_on=["game_id", "team"], right_index=True, how="left")
    pg["team_td"] = pg.team_td.fillna(0)
    w = m["xtd_weight"]
    pg["blend"] = w * pg.xtd + (1 - w) * pg.td
    pg["team_blend"] = w * pg.team_xtd + (1 - w) * pg.team_td
    pg["wt"] = m["recency_decay"] ** (cur - 1 - pg.week)

    # Only the player's current team counts (handles mid-season trades).
    latest_team = pg.sort_values("week").groupby("pid").team.last()
    pg = pg[pg.team == pg.pid.map(latest_team)]

    priced = set(cfg.get("market_odds", {}).get(str(cur), {}))
    rows = []
    for pid, d in pg.groupby("pid"):
        key = f"{d.name.iloc[-1]}|{latest_team[pid]}"
        if d.week.max() < cur - 1 - m["stale_weeks"]:
            continue
        if len(d) < m["min_games"] and key not in priced:
            continue
        share = (d.wt * d.blend).sum() / max((d.wt * d.team_blend).sum(), 1e-9)
        rows.append({
            "pid": pid, "name": d.name.iloc[-1], "team": latest_team[pid],
            "games": len(d), "last_week": int(d.week.max()), "td": int(d.td.sum()),
            "xtd": round(d.xtd.sum(), 2), "rz": int(d.rz.sum()), "gl": int(d.gl.sum()),
            "share": share,
        })
    return pd.DataFrame(rows).set_index("pid")


def td_per_point(pbp, games):
    done = games[games.home_score.notna()]
    pts = done.home_score.sum() + done.away_score.sum()
    tds = (pbp.rush_touchdown == 1).sum() + (pbp.pass_touchdown == 1).sum()
    return tds / pts


def probability_table(players, sched, tdpp, cfg):
    """P(player scores a qualifying TD) for each remaining week. 0 on byes."""
    weeks = list(range(cfg["current_week"], cfg["last_week"] + 1))
    sched = sched.set_index(["week", "team"])
    probs = pd.DataFrame(0.0, index=players.index, columns=weeks)
    for pid, pl in players.iterrows():
        for wk in weeks:
            if (wk, pl.team) not in sched.index:
                continue
            lam = pl.share * sched.loc[(wk, pl.team), "pts"] * tdpp
            probs.loc[pid, wk] = 1 - math.exp(-lam)
    return probs


def key_of(players):
    return players.name + "|" + players.team


def apply_market_and_injuries(probs, players, cfg):
    keys = key_of(players)
    lookup = {k: pid for pid, k in keys.items()}
    notes = []
    for wk, odds in cfg.get("market_odds", {}).items():
        wk = int(wk)
        for k, american in odds.items():
            if k not in lookup:
                notes.append(f"market: {k} not found in play-by-play")
                continue
            imp = (-american / (-american + 100)) if american < 0 else 100 / (american + 100)
            mkt = imp * cfg["vig_factor"]
            pid = lookup[k]
            mw = cfg["market_weight"]
            probs.loc[pid, wk] = mw * mkt + (1 - mw) * probs.loc[pid, wk]
    for wk, inj in cfg.get("injuries", {}).items():
        for k, mult in inj.items():
            if k in lookup:
                probs.loc[lookup[k], int(wk)] *= mult
            else:
                notes.append(f"injury: {k} not found in play-by-play")
    return notes


def resolve_used(used, players):
    keys = key_of(players)
    lookup = {k: pid for pid, k in keys.items()}
    pids, missing = set(), []
    for k in used:
        if k in lookup:
            pids.add(lookup[k])
        else:
            missing.append(k)
    return pids, missing


def best_path(probs, avail, weeks, cfg, fixed=None):
    """Max sum of discounted log-survival over remaining weeks, no repeats.

    fixed = (week, pid) forces a pick. Returns {week: pid} and the objective.
    """
    disc = cfg["model"]["future_week_discount"]
    pool = [p for p in avail if p in probs.index]
    # Only the top candidates matter; keeps the matrix small.
    top = probs.loc[pool, weeks].max(axis=1).sort_values(ascending=False)
    pool = list(top.index[: cfg["model"]["candidate_pool"]])
    if fixed and fixed[1] not in pool:
        pool.append(fixed[1])
    p = probs.loc[pool, weeks].to_numpy().clip(1e-4, 0.999)
    gain = np.log(p) * np.array([disc ** i for i in range(len(weeks))])
    if fixed:
        wi = weeks.index(fixed[0])
        gain[:, wi] = -1e6
        gain[pool.index(fixed[1]), wi] = math.log(p[pool.index(fixed[1]), wi])
    rows, cols = linear_sum_assignment(-gain)
    path = {weeks[c]: pool[r] for r, c in zip(rows, cols)}
    return path, gain[rows, cols].sum()


def plan(cfg, probs, players):
    weeks = list(range(cfg["current_week"], cfg["last_week"] + 1))
    wk = weeks[0]
    entries = {}
    for name, e in cfg["entries"].items():
        used, missing = resolve_used(e["used"], players)
        if missing:
            print(f"WARNING {name}: could not resolve used picks {missing}")
        entries[name] = [p for p in probs.index if p not in used]

    # Future value of each entry for every plausible Week-N pick.
    names = list(entries)
    cand = {}
    for n in names:
        now = probs.loc[entries[n], wk].sort_values(ascending=False).head(12)
        cand[n] = {pid: best_path(probs, entries[n], weeks, cfg, fixed=(wk, pid))
                   for pid in now.index if now[pid] > 0}

    # Pick the pair that maximizes both entries' season value plus the odds
    # that at least one survives this week (same player => fully correlated).
    best = None
    a, b = names[:2]
    for pa, (path_a, va) in cand[a].items():
        for pb, (path_b, vb) in cand[b].items():
            qa, qb = probs.loc[pa, wk], probs.loc[pb, wk]
            same_game = players.loc[pa, "team"] == players.loc[pb, "team"]
            either = qa if pa == pb else 1 - (1 - qa) * (1 - qb)
            if same_game and pa != pb:
                either -= 0.03  # same team: modest positive correlation
            score = va + vb + math.log(either)
            if best is None or score > best[0]:
                best = (score, {a: (pa, path_a), b: (pb, path_b)}, either)
    return best, cand


def label(pid, players):
    pl = players.loc[pid]
    return f"{pl['name']} ({pl.team})"


def report(cfg, probs, players, sched, best, cand, notes):
    wk = cfg["current_week"]
    weeks = list(range(wk, cfg["last_week"] + 1))
    _, picks, either = best
    s = sched.set_index(["week", "team"])
    L = []
    L.append(f"# {cfg['contest']}: Week {wk} plan\n")
    L.append("Projected P(TD) blends an opportunity-based model (red-zone and goal-line "
             "usage from 2026 play-by-play, scaled by Vegas implied team totals) 50/50 "
             "with de-vigged sportsbook prices where available.\n")
    L.append(f"## Week {wk} picks\n")
    L.append("| Entry | Primary | Opp | Kickoff | P(TD) | Alternate |")
    L.append("|---|---|---|---|---|---|")
    taken = {pid for pid, _ in picks.values()}
    for n, (pid, path) in picks.items():
        team = players.loc[pid, "team"]
        g = s.loc[(wk, team)]
        used, _ = resolve_used(cfg["entries"][n]["used"], players)
        # Alternate: best remaining player who isn't in this entry's future path
        # and isn't the other entry's primary.
        future = set(path.values())
        alt_pool = probs.loc[[p for p in probs.index if p not in used and p not in future
                              and p not in taken], wk].sort_values(ascending=False)
        alt = alt_pool.index[0]
        L.append(f"| {n} | **{label(pid, players)}** | {g.opp} | {g.gameday} {g.gametime} ET "
                 f"| {probs.loc[pid, wk]:.0%} | {label(alt, players)} ({alt_pool.iloc[0]:.0%}) |")
    L.append(f"\nP(at least one entry survives Week {wk}): **{either:.0%}**\n")

    L.append(f"## Week {wk} board (all players)\n")
    L.append("| Player | Opp | Team pts | P(TD) | Season TD | RZ opp | GL opp | "
             + " | ".join(cfg["entries"]) + " |")
    L.append("|---|---|---|---|---|---|---|" + "---|" * len(cfg["entries"]))
    used_sets = {n: resolve_used(e["used"], players)[0] for n, e in cfg["entries"].items()}
    for pid, p in probs[wk].sort_values(ascending=False).head(30).items():
        pl = players.loc[pid]
        g = s.loc[(wk, pl.team)]
        avail = " | ".join("used" if pid in used_sets[n] else "ok" for n in cfg["entries"])
        L.append(f"| {label(pid, players)} | {g.opp} | {g.pts:.1f} | {p:.0%} | {pl.td} "
                 f"| {pl.rz} | {pl.gl} | {avail} |")

    for n, (pid, path) in picks.items():
        L.append(f"\n## {n}: projected path (re-run every week)\n")
        L.append("| Week | Pick | Opp | P(TD) | Line source |")
        L.append("|---|---|---|---|---|")
        surv = 1.0
        for w in weeks:
            q = path[w]
            team = players.loc[q, "team"]
            g = s.loc[(w, team)] if (w, team) in s.index else None
            surv *= probs.loc[q, w]
            L.append(f"| {w} | {label(q, players)} | {g.opp if g is not None else 'BYE'} "
                     f"| {probs.loc[q, w]:.0%} | {g.src if g is not None else '-'} |")
        L.append(f"\nCumulative survival through Week {cfg['last_week']} if the path holds: "
                 f"{surv:.1%}")

    L.append(f"\n## Week {wk} alternatives by entry (season value if you pick him now)\n")
    for n, c in cand.items():
        top = max(v for _, v in c.values())
        L.append(f"**{n}**: " + ", ".join(
            f"{label(pid, players)} {probs.loc[pid, wk]:.0%} (value {v - top:+.2f})"
            for pid, (_, v) in sorted(c.items(), key=lambda kv: -kv[1][1])[:6]))
        L.append("")
    if notes:
        L.append("## Data notes\n")
        L += [f"- {x}" for x in notes]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=ROOT / "config.json")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text())

    games, pbp = load(args.refresh)
    pg, _, _ = opportunities(pbp)
    off, dfn, lg = team_ratings(games, cfg)
    sched = implied_points(games, off, dfn, lg, cfg)
    sched = sched[sched.week >= cfg["current_week"]]
    players = player_shares(pg, pbp, cfg)
    tdpp = td_per_point(pbp, games)
    probs = probability_table(players, sched, tdpp, cfg)
    notes = apply_market_and_injuries(probs, players, cfg)
    best, cand = plan(cfg, probs, players)

    OUT.mkdir(exist_ok=True)
    md = report(cfg, probs, players, sched, best, cand, notes)
    path = OUT / f"week{cfg['current_week']:02d}_plan.md"
    path.write_text(md)
    board = probs.join(players[["name", "team", "td", "rz", "gl"]])
    board.sort_values(cfg["current_week"], ascending=False).round(3).to_csv(
        OUT / f"week{cfg['current_week']:02d}_probabilities.csv")
    print(md)


if __name__ == "__main__":
    main()
