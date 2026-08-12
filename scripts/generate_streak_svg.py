#!/usr/bin/env python3
"""
Self-hosted GitHub streak + contribution graph generator.

Fetches contribution data directly from GitHub's GraphQL API and renders
two SVGs locally — no dependency on any third-party rendering service,
so it can't go down because someone else's server is rate-limited.

Env vars:
    GH_TOKEN        Personal access token with `read:user` scope (required)
    STREAK_USERNAME GitHub username to report on (default: below)
"""

import json
import os
import urllib.request
from datetime import date

GITHUB_USERNAME = os.environ.get("STREAK_USERNAME", "utsav8143")
TOKEN = os.environ["GH_TOKEN"]

OUT_STATS = os.environ.get("OUT_STATS", "assets/streak-stats.svg")
OUT_GRAPH = os.environ.get("OUT_GRAPH", "assets/contribution-graph.svg")

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_contributions():
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": GITHUB_USERNAME}}).encode(),
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": GITHUB_USERNAME,
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    calendar = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = calendar["weeks"]
    days = []
    for week in weeks:
        for d in week["contributionDays"]:
            days.append({"date": d["date"], "count": d["contributionCount"]})
    days.sort(key=lambda x: x["date"])
    return days, weeks, calendar["totalContributions"]


def compute_streaks(days):
    today_str = date.today().isoformat()
    working = days[:]
    # If today hasn't ended yet and has 0 contributions so far, don't let it
    # break an in-progress streak.
    if working and working[-1]["date"] == today_str and working[-1]["count"] == 0:
        working = working[:-1]

    current = 0
    current_end = None
    for d in reversed(working):
        if d["count"] > 0:
            if current == 0:
                current_end = d["date"]
            current += 1
        else:
            break
    current_start = None
    if current > 0:
        idx = len(working) - current
        current_start = working[idx]["date"]

    longest = 0
    run = 0
    run_start = None
    best_start = best_end = None
    for d in days:
        if d["count"] > 0:
            if run == 0:
                run_start = d["date"]
            run += 1
            if run > longest:
                longest = run
                best_start, best_end = run_start, d["date"]
        else:
            run = 0

    return {
        "current": current,
        "current_start": current_start,
        "current_end": current_end,
        "longest": longest,
        "longest_start": best_start,
        "longest_end": best_end,
    }


def fmt_range(start, end):
    if not start:
        return "—"
    if start == end:
        return date.fromisoformat(start).strftime("%b %-d, %Y")
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    if s.year == e.year:
        return f"{s.strftime('%b %-d')} – {e.strftime('%b %-d, %Y')}"
    return f"{s.strftime('%b %-d, %Y')} – {e.strftime('%b %-d, %Y')}"


STATS_TEMPLATE = """<svg width="700" height="200" viewBox="0 0 700 200" xmlns="http://www.w3.org/2000/svg">
<style>
  :root {{
    --bg: #ffffff; --border: #d8dee4; --title: #24292f;
    --num: #E2711D; --label: #57606a; --sub: #8b949e; --divider: #d8dee4;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117; --border: #30363d; --title: #e6edf3;
      --num: #f0883e; --label: #8b949e; --sub: #6e7681; --divider: #30363d;
    }}
  }}
  .card {{ font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; }}
  .num {{ font-size: 34px; font-weight: 700; fill: var(--num); }}
  .label {{ font-size: 13px; font-weight: 600; fill: var(--label); text-transform: uppercase; letter-spacing: 0.04em; }}
  .sub {{ font-size: 12px; fill: var(--sub); }}
  .title {{ font-size: 13px; font-weight: 700; fill: var(--title); }}
</style>
<rect class="card" x="0.5" y="0.5" width="699" height="199" rx="10" fill="var(--bg)" stroke="var(--border)"/>
<g class="card" text-anchor="middle">
  <text x="116" y="70" class="num">{total}</text>
  <text x="116" y="96" class="label">Total Contributions</text>
  <text x="116" y="118" class="sub">{total_range}</text>

  <line x1="233" y1="34" x2="233" y2="166" stroke="var(--divider)" stroke-width="1"/>

  <text x="350" y="46" class="title">🔥 Current Streak</text>
  <text x="350" y="90" class="num">{current}</text>
  <text x="350" y="112" class="label">Days</text>
  <text x="350" y="132" class="sub">{current_range}</text>

  <line x1="467" y1="34" x2="467" y2="166" stroke="var(--divider)" stroke-width="1"/>

  <text x="584" y="70" class="num">{longest}</text>
  <text x="584" y="96" class="label">Longest Streak</text>
  <text x="584" y="118" class="sub">{longest_range}</text>
</g>
</svg>
"""


def render_stats(total, total_range, streaks):
    return STATS_TEMPLATE.format(
        total=total,
        total_range=total_range,
        current=streaks["current"],
        current_range=fmt_range(streaks["current_start"], streaks["current_end"]),
        longest=streaks["longest"],
        longest_range=fmt_range(streaks["longest_start"], streaks["longest_end"]),
    )


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CELL = 11
GAP = 3
STEP = CELL + GAP
LEFT_PAD = 30
TOP_PAD = 24


def render_graph(weeks):
    n_weeks = len(weeks)
    width = LEFT_PAD + n_weeks * STEP + 10
    height = TOP_PAD + 7 * STEP + 10

    counts = [d["contributionCount"] for w in weeks for d in w["contributionDays"] if d["contributionCount"] > 0]
    m = max(counts) if counts else 1
    t1, t2, t3 = m * 0.25, m * 0.5, m * 0.75

    def level(c):
        if c == 0:
            return 0
        if c <= t1:
            return 1
        if c <= t2:
            return 2
        if c <= t3:
            return 3
        return 4

    cells = []
    month_labels = []
    last_month = None
    for wi, week in enumerate(weeks):
        x = LEFT_PAD + wi * STEP
        first_day = week["contributionDays"][0]["date"] if week["contributionDays"] else None
        if first_day:
            mo = date.fromisoformat(first_day).month
            if mo != last_month:
                month_labels.append((x, MONTHS[mo - 1]))
                last_month = mo
        for di, day in enumerate(week["contributionDays"]):
            y = TOP_PAD + di * STEP
            lvl = level(day["contributionCount"])
            cells.append(
                f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" '
                f'class="lvl{lvl}"><title>{day["date"]}: {day["contributionCount"]} contributions</title></rect>'
            )

    months_svg = "".join(f'<text x="{x}" y="14" class="month">{name}</text>' for x, name in month_labels)

    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
<style>
  :root {{
    --bg: #ffffff; --border: #d8dee4; --month: #57606a;
    --l0: #ebedf0; --l1: #E9D6BE; --l2: #EFB37E; --l3: #E88F3C; --l4: #C75F13;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117; --border: #30363d; --month: #8b949e;
      --l0: #161b22; --l1: #3d2913; --l2: #7a4a1c; --l3: #b56a20; --l4: #f0883e;
    }}
  }}
  .month {{ font: 600 11px -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; fill: var(--month); }}
  .lvl0 {{ fill: var(--l0); }} .lvl1 {{ fill: var(--l1); }} .lvl2 {{ fill: var(--l2); }}
  .lvl3 {{ fill: var(--l3); }} .lvl4 {{ fill: var(--l4); }}
</style>
<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="var(--bg)" stroke="var(--border)"/>
{months_svg}
{''.join(cells)}
</svg>
"""


def main():
    days, weeks, total = fetch_contributions()
    streaks = compute_streaks(days)
    total_range = fmt_range(days[0]["date"], days[-1]["date"]) if days else "—"

    os.makedirs(os.path.dirname(OUT_STATS), exist_ok=True)
    with open(OUT_STATS, "w") as f:
        f.write(render_stats(total, total_range, streaks))

    os.makedirs(os.path.dirname(OUT_GRAPH), exist_ok=True)
    with open(OUT_GRAPH, "w") as f:
        f.write(render_graph(weeks))

    print(f"Wrote {OUT_STATS} and {OUT_GRAPH}")
    print(f"Current streak: {streaks['current']} days | Longest: {streaks['longest']} days | Total: {total}")


if __name__ == "__main__":
    main()
