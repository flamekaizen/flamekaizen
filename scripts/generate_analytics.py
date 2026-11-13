#!/usr/bin/env python3
"""
FLAMEKAIZEN // Profile Analytics Engine
=======================================

Self-hosted replacement for third-party README widgets (which go down, get
rate-limited or lose their hosting). Pulls the full contribution history from
the GitHub GraphQL API and renders a suite of themed, animated SVG panels into
``analytics/``.

Pure standard library — no pip install needed.

Usage:
    GITHUB_TOKEN=... python scripts/generate_analytics.py [username]

Privacy: private repositories only ever contribute to *aggregate* numbers
(language shares, repo counts). No private repository name is ever written.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

# ─── Theme (matches the existing README: dark, flame red accent) ─────────────
BG = "#0D1117"
PANEL = "#0D1117"
TILE = "#161B22"
BORDER = "#30363D"
GRID = "#21262D"
TEXT = "#C9D1D9"
MUTED = "#8B949E"
WHITE = "#F0F6FC"
ACCENT = "#F73859"
ACCENT2 = "#FF8A5B"
BLUE = "#58A6FF"
GREEN = "#2EA043"
PURPLE = "#BC8CFF"
YELLOW = "#E3B341"
SANS = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "'JetBrains Mono', 'Fira Code', 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"
HEAT = ["#161B22", "#4A1420", "#7D1D31", "#B82843", "#F73859"]

OUT = Path(__file__).resolve().parent.parent / "analytics"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ═════════════════════════════════════════════════════════════════════════════
#  DATA LAYER
# ═════════════════════════════════════════════════════════════════════════════
def gql(query: str, variables: dict | None = None) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-analytics"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch(login: str) -> dict:
    head = gql(
        """query($l:String!){user(login:$l){createdAt name
            followers{totalCount} following{totalCount}
            contributionsCollection{contributionYears}}}""",
        {"l": login},
    )["user"]

    # Repositories (owned, non-fork), paginated
    repos, cursor = [], None
    while True:
        page = gql(
            """query($l:String!,$c:String){user(login:$l){repositories(
                ownerAffiliations:OWNER,isFork:false,first:100,after:$c){
                pageInfo{hasNextPage endCursor}
                nodes{name isPrivate stargazerCount forkCount createdAt pushedAt
                  languages(first:20,orderBy:{field:SIZE,direction:DESC}){
                    edges{size node{name color}}}}}}}""",
            {"l": login, "c": cursor},
        )["user"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    # Contribution collections — one aliased query covering every year
    created = datetime.fromisoformat(head["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    parts = []
    for y in range(created.year, now.year + 1):
        start = max(created, datetime(y, 1, 1, tzinfo=timezone.utc))
        end = min(now, datetime(y, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        parts.append(
            f'y{y}:contributionsCollection(from:"{start.isoformat()}",to:"{end.isoformat()}"){{'
            "totalCommitContributions totalIssueContributions totalPullRequestContributions "
            "totalPullRequestReviewContributions totalRepositoryContributions restrictedContributionsCount "
            "contributionCalendar{totalContributions weeks{contributionDays{date contributionCount}}}}"
        )
    years = gql(f'query($l:String!){{user(login:$l){{{" ".join(parts)}}}}}', {"l": login})["user"]
    return {"head": head, "repos": repos, "years": years, "created": created.date(), "now": now}


# ═════════════════════════════════════════════════════════════════════════════
#  ANALYSIS LAYER
# ═════════════════════════════════════════════════════════════════════════════
def analyse(raw: dict) -> dict:
    today = raw["now"].date()
    daily: dict[date, int] = {}
    comp = Counter()
    for col in raw["years"].values():
        comp["Commits"] += col["totalCommitContributions"]
        comp["Pull requests"] += col["totalPullRequestContributions"]
        comp["Issues"] += col["totalIssueContributions"]
        comp["Code reviews"] += col["totalPullRequestReviewContributions"]
        comp["Repos created"] += col["totalRepositoryContributions"]
        comp["Private work"] += col["restrictedContributionsCount"]
        for w in col["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                dt = date.fromisoformat(d["date"])
                if dt <= today:
                    daily[dt] = max(daily.get(dt, 0), d["contributionCount"])

    start = min(raw["created"], min(daily) if daily else today)
    days = [start + timedelta(i) for i in range((today - start).days + 1)]
    counts = [daily.get(d, 0) for d in days]
    total = sum(counts)

    # Streaks ---------------------------------------------------------------
    longest = (0, None, None)
    run, run_start = 0, None
    for d, c in zip(days, counts):
        if c > 0:
            run_start = d if run == 0 else run_start
            run += 1
            if run > longest[0]:
                longest = (run, run_start, d)
        else:
            run = 0
    cur, i = 0, len(counts) - 1
    if counts and counts[-1] == 0:  # today not yet active -> streak survives until midnight
        i -= 1
    cur_end = days[i] if i >= 0 else None
    while i >= 0 and counts[i] > 0:
        cur += 1
        i -= 1
    current = (cur, days[i + 1] if cur else None, cur_end if cur else None)

    # Windows ---------------------------------------------------------------
    last365 = counts[-365:]
    prev365 = counts[-730:-365]
    last30, prev30 = sum(counts[-30:]), sum(counts[-60:-30])
    active = [c for c in counts if c > 0]
    active365 = sum(1 for c in last365 if c > 0)
    peak_i = max(range(len(counts)), key=lambda k: counts[k]) if counts else 0

    def pct_change(a, b):
        return None if b == 0 else (a - b) / b * 100

    # Distribution statistics (over the last 365 days) -----------------------
    x = last365
    mu = statistics.fmean(x) if x else 0
    sd = statistics.pstdev(x) if len(x) > 1 else 0
    skew = (sum((v - mu) ** 3 for v in x) / len(x)) / sd**3 if sd else 0
    srt = sorted(x)
    n = len(srt)
    gini = (2 * sum((k + 1) * v for k, v in enumerate(srt)) / (n * sum(srt)) - (n + 1) / n) if sum(srt) else 0
    burst = (sd - mu) / (sd + mu) if (sd + mu) else 0  # Goh & Barabási burstiness, -1 regular .. +1 bursty
    if sd and n > 1:
        ac1 = sum((x[k] - mu) * (x[k + 1] - mu) for k in range(n - 1)) / ((n - 1) * sd**2)
    else:
        ac1 = 0
    act365 = [v for v in x if v > 0]
    p90 = sorted(act365)[int(0.9 * (len(act365) - 1))] if act365 else 0

    # Weekday profile (lifetime) + Shannon entropy regularity -----------------
    wk = [0] * 7
    for d, c in zip(days, counts):
        wk[d.weekday()] += c
    wsum = sum(wk)
    ent = -sum((v / wsum) * math.log2(v / wsum) for v in wk if v) / math.log2(7) if wsum else 0

    # Monthly series (lifetime) ----------------------------------------------
    monthly: dict[tuple[int, int], int] = defaultdict(int)
    for d, c in zip(days, counts):
        monthly[(d.year, d.month)] += c
    mkeys = []
    y, m = start.year, start.month
    while (y, m) <= (today.year, today.month):
        mkeys.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    mvals = [monthly[k] for k in mkeys]

    # OLS on the last 12 complete months
    reg_keys = mkeys[-13:-1] if len(mkeys) > 1 else mkeys
    ry = [monthly[k] for k in reg_keys]
    rx = list(range(len(ry)))
    slope = icpt = r2 = 0.0
    if len(ry) >= 3:
        mx, my = statistics.fmean(rx), statistics.fmean(ry)
        sxx = sum((a - mx) ** 2 for a in rx)
        sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
        slope = sxy / sxx if sxx else 0
        icpt = my - slope * mx
        ss_tot = sum((b - my) ** 2 for b in ry)
        ss_res = sum((b - (icpt + slope * a)) ** 2 for a, b in zip(rx, ry))
        r2 = 1 - ss_res / ss_tot if ss_tot else 0

    # Temporal fingerprint: weekday × last 12 months -------------------------
    fp_keys = mkeys[-12:]
    fp = [[0] * len(fp_keys) for _ in range(7)]
    kidx = {k: j for j, k in enumerate(fp_keys)}
    for d, c in zip(days, counts):
        j = kidx.get((d.year, d.month))
        if j is not None:
            fp[d.weekday()][j] += c

    # Languages: repo-normalised share --------------------------------------
    # Each repo contributes a total weight of 1 split by its byte fractions,
    # so a single 70 MB notebook dump can't drown out everything else.
    lang_w: dict[str, float] = defaultdict(float)
    lang_n: Counter = Counter()
    lang_color: dict[str, str] = {}
    lang_repos = 0
    for r in raw["repos"]:
        edges = r["languages"]["edges"]
        tot = sum(e["size"] for e in edges)
        if not tot:
            continue
        lang_repos += 1
        for e in edges:
            nm = e["node"]["name"]
            lang_w[nm] += e["size"] / tot
            lang_n[nm] += 1
            lang_color[nm] = e["node"]["color"] or MUTED
    lw_tot = sum(lang_w.values()) or 1
    langs = sorted(
        ((k, v / lw_tot * 100, lang_n[k], lang_color[k]) for k, v in lang_w.items()),
        key=lambda t: -t[1],
    )

    repos = raw["repos"]
    return {
        "login": raw["login"],
        "today": today,
        "created": raw["created"],
        "days": days,
        "counts": counts,
        "total": total,
        "year_total": sum(last365),
        "yoy": pct_change(sum(last365), sum(prev365)) if len(prev365) == 365 else None,
        "current": current,
        "longest": longest,
        "active_days": len(active),
        "active365": active365,
        "peak": (counts[peak_i], days[peak_i]) if counts else (0, today),
        "mean_active": statistics.fmean(active) if active else 0,
        "sd_active": statistics.pstdev(active) if len(active) > 1 else 0,
        "last30": last30,
        "momentum": pct_change(last30, prev30),
        "mu": mu, "sd": sd, "skew": skew, "gini": gini, "burst": burst, "ac1": ac1,
        "p90": p90, "median_active": statistics.median(act365) if act365 else 0,
        "act365": act365,
        "weekday": wk, "entropy": ent,
        "mkeys": mkeys, "mvals": mvals,
        "reg": (slope, icpt, r2, len(reg_keys)),
        "fp": fp, "fp_keys": fp_keys,
        "comp": comp,
        "langs": langs, "lang_repos": lang_repos,
        "repo_count": len(repos),
        "public_repos": sum(1 for r in repos if not r["isPrivate"]),
        "stars": sum(r["stargazerCount"] for r in repos if not r["isPrivate"]),
        "generated": raw["now"],
    }


# ═════════════════════════════════════════════════════════════════════════════
#  SVG TOOLKIT
# ═════════════════════════════════════════════════════════════════════════════
STYLE = f"""
<style>
  .t  {{ font-family:{SANS}; fill:{TEXT}; }}
  .m  {{ font-family:{MONO}; fill:{MUTED}; }}
  .h  {{ font-family:{MONO}; fill:{WHITE}; font-weight:700; letter-spacing:2px; }}
  .v  {{ font-family:{MONO}; fill:{WHITE}; font-weight:700; }}
  .lbl{{ font-family:{MONO}; fill:{MUTED}; font-size:10px; letter-spacing:1.2px; }}
  .fade {{ animation: fade .9s ease-out both; }}
  .grow {{ transform-box: fill-box; transform-origin: 50% 100%; animation: grow 1s cubic-bezier(.2,.8,.2,1) both; }}
  .growx{{ transform-box: fill-box; transform-origin: 0% 50%;  animation: growx 1.1s cubic-bezier(.2,.8,.2,1) both; }}
  .draw {{ stroke-dasharray: 1; animation: draw 2.2s ease-out both; }}
  .pulse{{ animation: pulse 1.6s ease-in-out infinite; }}
  .scan {{ animation: scan 6s linear infinite; }}
  @keyframes fade  {{ from {{ opacity:0; }} }}
  @keyframes grow  {{ from {{ transform: scaleY(0); }} }}
  @keyframes growx {{ from {{ transform: scaleX(0); }} }}
  @keyframes draw  {{ from {{ stroke-dashoffset: 1; }} }}
  @keyframes pulse {{ 50% {{ opacity:.25; }} }}
  @keyframes scan  {{ from {{ transform: translateY(-40px); }} to {{ transform: translateY(var(--h)); }} }}
</style>"""


def f(v: float, nd: int = 2) -> str:
    return f"{v:.{nd}f}"


def esc(s) -> str:
    return escape(str(s))


def text(x, y, s, cls="t", size=12, anchor="start", fill=None, weight=None, extra=""):
    a = f' fill="{fill}"' if fill else ""
    w = f' font-weight="{weight}"' if weight else ""
    return f'<text x="{f(x,1)}" y="{f(y,1)}" class="{cls}" font-size="{size}" text-anchor="{anchor}"{a}{w} {extra}>{esc(s)}</text>'


def nice_max(v: float) -> float:
    if v <= 0:
        return 4
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 4, 5, 10):
        if m * e >= v:
            return m * e
    return 10 * e


def fmt_int(n) -> str:
    return f"{int(round(n)):,}"


def fmt_pct(p, signed=True) -> str:
    if p is None:
        return "n/a"
    return f"{p:+.0f}%" if signed else f"{p:.0f}%"


def fmt_date(d: date | None, year=True) -> str:
    if not d:
        return "—"
    return f"{MONTHS[d.month-1]} {d.day}" + (f", {d.year}" if year else "")


def panel(w: int, h: int, code: str, title: str, subtitle: str, body: str, gen: datetime) -> str:
    """Standard HUD frame: grid backdrop, corner brackets, header, scanline, footer."""
    c, L = ACCENT, 14
    corners = (
        f'<path d="M1.5 {L} V1.5 H{L} M{w-L} 1.5 H{w-1.5} V{L} M{w-1.5} {h-L} V{h-1.5} H{w-L} '
        f'M{L} {h-1.5} H1.5 V{h-L}" stroke="{c}" stroke-width="2" fill="none"/>'
    )
    stamp = gen.strftime("%Y-%m-%d %H:%M UTC")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">
<title>{esc(title)} — {esc(subtitle)}</title>
{STYLE}
<defs>
  <pattern id="g" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="{GRID}" stroke-width=".5" opacity=".55"/></pattern>
  <linearGradient id="scan" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ACCENT}" stop-opacity="0"/><stop offset="1" stop-color="{ACCENT}" stop-opacity=".07"/></linearGradient>
  <linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ACCENT}" stop-opacity=".45"/><stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></linearGradient>
  <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ACCENT}"/><stop offset="1" stop-color="#7D1D31"/></linearGradient>
  <linearGradient id="barx" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#7D1D31"/><stop offset="1" stop-color="{ACCENT}"/></linearGradient>
  <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <clipPath id="frame"><rect x="1" y="1" width="{w-2}" height="{h-2}" rx="8"/></clipPath>
</defs>
<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="8" fill="{PANEL}" stroke="{BORDER}"/>
<g clip-path="url(#frame)">
  <rect width="{w}" height="{h}" fill="url(#g)"/>
  <rect class="scan" style="--h:{h}px" x="0" y="0" width="{w}" height="40" fill="url(#scan)"/>
</g>
{corners}
<g class="fade">
  <circle class="pulse" cx="24" cy="27" r="4" fill="{ACCENT}" filter="url(#glow)"/>
  {text(36, 31, title.upper(), "h", 13)}
  {text(36, 47, subtitle, "m", 10.5)}
  {text(w-22, 31, code, "m", 10, "end", ACCENT, extra='letter-spacing="1.5"')}
  {text(w-22, 47, "SYNC " + stamp, "m", 9, "end")}
  <line x1="20" y1="58" x2="{w-20}" y2="58" stroke="{BORDER}"/>
  <line x1="20" y1="58" x2="90" y2="58" stroke="{ACCENT}" stroke-width="2"/>
</g>
{body}
</svg>
"""


def polyline(pts, **attrs) -> str:
    a = " ".join(f'{k.replace("_","-")}="{v}"' for k, v in attrs.items())
    return f'<polyline points="{" ".join(f"{f(x,1)},{f(y,1)}" for x, y in pts)}" {a}/>'


# ═════════════════════════════════════════════════════════════════════════════
#  PANELS
# ═════════════════════════════════════════════════════════════════════════════
def svg_overview(a: dict) -> str:
    W, H = 900, 262
    cur, lng = a["current"], a["longest"]
    age_years = (a["today"] - a["created"]).days / 365.25
    tiles = [
        ("LIFETIME CONTRIBS", fmt_int(a["total"]), f"since {fmt_date(a['created'])}", ACCENT, None),
        ("LAST 365 DAYS", fmt_int(a["year_total"]), f"YoY {fmt_pct(a['yoy'])}", WHITE, None),
        ("CURRENT STREAK", f"{cur[0]}d", f"{fmt_date(cur[1], False)} → {fmt_date(cur[2], False)}" if cur[0] else "start one today", GREEN,
         (cur[0] / lng[0]) if lng[0] else 0),
        ("LONGEST STREAK", f"{lng[0]}d", f"{fmt_date(lng[1], False)} → {fmt_date(lng[2])}" if lng[0] else "—", YELLOW, None),
        ("ACTIVE DAYS / 365", fmt_int(a["active365"]), f"{a['active365']/365*100:.1f}% duty cycle", BLUE, a["active365"] / 365),
        ("PEAK SINGLE DAY", fmt_int(a["peak"][0]), fmt_date(a["peak"][1]), ACCENT2, None),
        ("MEAN / ACTIVE DAY", f"{a['mean_active']:.2f}", f"σ = {a['sd_active']:.2f}", WHITE, None),
        ("30-DAY MOMENTUM", fmt_pct(a["momentum"]) if a["momentum"] is not None else ("▲ NEW" if a["last30"] else "—"),
         f"{a['last30']} vs prior 30d",
         GREEN if (a["momentum"] or 0) >= 0 else ACCENT, None),
        ("REPOSITORIES", fmt_int(a["repo_count"]), f"{a['public_repos']} public · {len(a['langs'])} langs", PURPLE, None),
        ("ACCOUNT AGE", f"{age_years:.1f}y", f"{(a['today']-a['created']).days:,} days in orbit", MUTED, None),
    ]
    cols, gx, gy, x0, y0 = 5, 10, 10, 20, 72
    tw = (W - 2 * x0 - (cols - 1) * gx) / cols
    th = 84
    out = []
    for k, (lbl, val, sub, col, prog) in enumerate(tiles):
        r, c = divmod(k, cols)
        x, y = x0 + c * (tw + gx), y0 + r * (th + gy)
        delay = f"{0.08 * k:.2f}s"
        g = [f'<g class="fade" style="animation-delay:{delay}">',
             f'<rect x="{f(x)}" y="{y}" width="{f(tw)}" height="{th}" rx="6" fill="{TILE}" stroke="{GRID}"/>',
             f'<rect x="{f(x)}" y="{y+10}" width="2.5" height="18" fill="{col}"/>',
             text(x + 12, y + 23, lbl, "lbl", 9.5),
             text(x + 12, y + 55, val, "v", 24, fill=col if col not in (WHITE, MUTED) else WHITE),
             text(x + 12, y + 73, sub, "m", 9.5)]
        if prog is not None:
            pw = tw - 24
            g.append(f'<rect x="{f(x+12)}" y="{y+78}" width="{f(pw)}" height="2" fill="{GRID}"/>')
            g.append(f'<rect class="growx" x="{f(x+12)}" y="{y+78}" width="{f(pw*min(prog,1))}" height="2" fill="{col}"/>')
        g.append("</g>")
        out.append("".join(g))
    return panel(W, H, "MOD-00 // TELEMETRY", "System Telemetry",
                 "core contribution KPIs · full account history · auto-refreshed daily", "\n".join(out), a["generated"])


def svg_activity(a: dict, n_days: int = 365) -> str:
    W, H = 900, 340
    days, counts = a["days"][-n_days:], a["counts"][-n_days:]
    full = a["counts"]
    off = len(full) - len(counts)
    ma7 = [statistics.fmean(full[max(0, off + i - 6): off + i + 1]) for i in range(len(counts))]
    ema, alpha, e = [], 2 / (28 + 1), None
    for v in full:
        e = v if e is None else alpha * v + (1 - alpha) * e
        ema.append(e)
    ema = ema[off:]

    x0, x1, y0, y1 = 58, W - 24, 92, H - 52
    ymax = nice_max(max(counts + [1]))
    n = len(counts)
    bw = (x1 - x0) / n
    X = lambda i: x0 + bw * (i + 0.5)
    Y = lambda v: y1 - (v / ymax) * (y1 - y0)

    out = []
    for k in range(5):  # grid
        v = ymax * k / 4
        yy = Y(v)
        out.append(f'<line x1="{x0}" y1="{f(yy)}" x2="{x1}" y2="{f(yy)}" stroke="{GRID}" stroke-dasharray="{"0" if k==0 else "3 4"}"/>')
        out.append(text(x0 - 10, yy + 4, f"{v:g}", "m", 10, "end"))
    for i, d in enumerate(days):  # month ticks
        if d.day == 1:
            out.append(f'<line x1="{f(X(i))}" y1="{y1}" x2="{f(X(i))}" y2="{y1+5}" stroke="{MUTED}"/>')
            out.append(text(X(i), y1 + 19, f"{MONTHS[d.month-1]} '{d.year%100:02d}", "m", 10, "middle"))
    # daily bars
    bars = []
    for i, c in enumerate(counts):
        if c:
            bars.append(f'<rect x="{f(x0 + bw*i + bw*0.18)}" y="{f(Y(c))}" width="{f(bw*0.64)}" height="{f(y1-Y(c))}" fill="{ACCENT}" opacity=".28" rx="1"/>')
    out.append(f'<g class="grow">{"".join(bars)}</g>')
    # MA area + line, EMA line
    pts = [(X(i), Y(v)) for i, v in enumerate(ma7)]
    area = f"M{f(X(0))},{y1} " + " ".join(f"L{f(px)},{f(py)}" for px, py in pts) + f" L{f(X(n-1))},{y1} Z"
    out.append(f'<path class="fade" d="{area}" fill="url(#area)"/>')
    out.append(polyline([(X(i), Y(v)) for i, v in enumerate(ema)], fill="none", stroke=BLUE, stroke_width="1.6",
                        stroke_dasharray="5 4", opacity=".9"))
    out.append(polyline(pts, pathLength="1", **{"class": "draw"}, fill="none", stroke=ACCENT, stroke_width="2.4",
                        stroke_linejoin="round", filter="url(#glow)"))
    # peak marker
    pk = max(range(n), key=lambda i: counts[i])
    if counts[pk]:
        px, py = X(pk), Y(counts[pk])
        anchor = "end" if px > W - 160 else "start"
        dx = -10 if anchor == "end" else 10
        out.append(f'<g class="fade" style="animation-delay:1.4s"><circle cx="{f(px)}" cy="{f(py)}" r="4.5" fill="{BG}" stroke="{YELLOW}" stroke-width="2"/>'
                   f'<circle class="pulse" cx="{f(px)}" cy="{f(py)}" r="9" fill="none" stroke="{YELLOW}" opacity=".6"/>'
                   + text(px + dx, py - 8, f"PEAK {counts[pk]} · {fmt_date(days[pk], False)}", "m", 10, anchor, YELLOW) + "</g>")
    # legend + window stats
    tot, act = sum(counts), sum(1 for c in counts if c)
    lg = [(ACCENT, "7-day moving avg", None), (BLUE, "28-day EMA", "5 4"), (ACCENT, "daily count", "bar")]
    lx = x0
    for col, name, kind in lg:
        if kind == "bar":
            out.append(f'<rect x="{lx}" y="70" width="10" height="10" fill="{col}" opacity=".35"/>')
        else:
            out.append(f'<line x1="{lx}" y1="75" x2="{lx+16}" y2="75" stroke="{col}" stroke-width="2.2" stroke-dasharray="{kind or 0}"/>')
        out.append(text(lx + 22, 79, name, "m", 10))
        lx += 22 + len(name) * 6.4 + 22
    out.append(text(x1, 79, f"Σ {tot}  ·  active {act}/{n}d  ·  μ {tot/n:.2f}/day  ·  EMA now {ema[-1]:.2f}", "m", 10, "end", TEXT))
    return panel(W, H, "MOD-01 // SIGNAL", "Contribution Activity",
                 f"last {n_days} days · daily counts with 7-day MA and 28-day exponential smoothing",
                 "\n".join(out), a["generated"])


def svg_trend(a: dict) -> str:
    W, H = 900, 300
    keys, vals = a["mkeys"], a["mvals"]
    x0, x1, y0, y1 = 58, W - 24, 84, H - 56
    ymax = nice_max(max(vals + [1]))
    n = len(vals)
    bw = (x1 - x0) / n
    X = lambda i: x0 + bw * (i + 0.5)
    Y = lambda v: y1 - (v / ymax) * (y1 - y0)
    out = []
    for k in range(5):
        v = ymax * k / 4
        out.append(f'<line x1="{x0}" y1="{f(Y(v))}" x2="{x1}" y2="{f(Y(v))}" stroke="{GRID}" stroke-dasharray="{"0" if k==0 else "3 4"}"/>')
        out.append(text(x0 - 10, Y(v) + 4, f"{v:g}", "m", 10, "end"))
    bars = []
    for i, ((yy, mm), v) in enumerate(zip(keys, vals)):
        last = i == n - 1
        if v:
            bars.append(f'<rect x="{f(x0+bw*i+bw*.16)}" y="{f(Y(v))}" width="{f(bw*.68)}" height="{f(y1-Y(v))}" rx="1.5" '
                        f'fill="url(#bar)" opacity="{".45" if last else "1"}"/>')
        if mm == 1 or i == 0:
            out.append(f'<line x1="{f(x0+bw*i)}" y1="{y0-6}" x2="{f(x0+bw*i)}" y2="{y1+4}" stroke="{BORDER}" stroke-dasharray="2 3"/>')
            out.append(text(x0 + bw * i + 4, y1 + 34, str(yy), "m", 10.5, fill=TEXT))
        if mm in (1, 4, 7, 10):
            out.append(text(X(i), y1 + 16, MONTHS[mm - 1][:1], "m", 9, "middle"))
    out.append(f'<g class="grow">{"".join(bars)}</g>')
    # yearly totals
    ytot = Counter()
    for (yy, _), v in zip(keys, vals):
        ytot[yy] += v
    # OLS fit over the last 12 complete months
    slope, icpt, r2, m = a["reg"]
    if m >= 3:
        s = n - 1 - m
        p0, p1 = (X(s), Y(max(icpt, 0))), (X(s + m - 1), Y(max(icpt + slope * (m - 1), 0)))
        out.append(f'<line class="fade" style="animation-delay:1s" x1="{f(p0[0])}" y1="{f(p0[1])}" x2="{f(p1[0])}" y2="{f(p1[1])}" stroke="{BLUE}" stroke-width="2" stroke-dasharray="6 4"/>')
        out.append(f'<circle cx="{f(p1[0])}" cy="{f(p1[1])}" r="3" fill="{BLUE}"/>')
    best = max(range(n), key=lambda i: vals[i])
    out.append(text(x0, 79, f"OLS (last 12 full months): slope {slope:+.1f}/mo · R² {r2:.2f}", "m", 10, fill=BLUE))
    out.append(text(x1, 79, "  ·  ".join(f"{y}: {ytot[y]}" for y in sorted(ytot)) +
                    f"  ·  best {MONTHS[keys[best][1]-1]} '{keys[best][0]%100:02d} ({vals[best]})", "m", 10, "end", TEXT))
    return panel(W, H, "MOD-02 // TREND", "Monthly Volume & Regression",
                 "lifetime contributions per month · dashed line = least-squares trend · faded bar = month in progress",
                 "\n".join(out), a["generated"])


def svg_fingerprint(a: dict) -> str:
    W, H = 445, 300
    fp, keys = a["fp"], a["fp_keys"]
    flat = sorted(v for row in fp for v in row if v)
    def level(v):
        if not v or not flat:
            return 0
        q = sum(1 for t in flat if t <= v) / len(flat)
        return 1 + min(3, int(q * 4 - 1e-9))
    x0, y0 = 58, 82
    cw = (W - x0 - 22) / max(len(keys), 1)
    ch = 21
    out = []
    for r in range(7):
        out.append(text(x0 - 10, y0 + r * ch + 15, WEEKDAYS[r], "m", 10, "end"))
        for c in range(len(keys)):
            v = fp[r][c]
            out.append(f'<rect class="fade" style="animation-delay:{(r+c)*0.03:.2f}s" x="{f(x0+c*cw+1.5)}" y="{y0+r*ch+1.5}" '
                       f'width="{f(cw-3)}" height="{ch-3}" rx="3" fill="{HEAT[level(v)]}"><title>{WEEKDAYS[r]} · '
                       f'{MONTHS[keys[c][1]-1]} {keys[c][0]}: {v}</title></rect>')
    for c, (yy, mm) in enumerate(keys):
        out.append(text(x0 + c * cw + cw / 2, y0 + 7 * ch + 15, MONTHS[mm - 1][:3], "m", 9, "middle"))
    lx = W - 22 - 5 * 14 - 34
    ly = H - 24
    out.append(text(lx - 6, ly + 9, "less", "m", 9, "end"))
    for k, col in enumerate(HEAT):
        out.append(f'<rect x="{lx + k*14}" y="{ly}" width="11" height="11" rx="2" fill="{col}"/>')
    out.append(text(lx + 5 * 14 + 2, ly + 9, "more", "m", 9))
    out.append(text(22, ly + 9, f"weekday × month · quartile-scaled", "m", 9))
    return panel(W, H, "MOD-03", "Temporal Fingerprint",
                 "when work happens · last 12 months", "\n".join(out), a["generated"])


def svg_radar(a: dict) -> str:
    W, H = 445, 300
    wk = a["weekday"]
    cx, cy, R = 150, 182, 92
    mx = max(wk + [1])
    out = []
    ang = lambda k: -math.pi / 2 + 2 * math.pi * k / 7
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = [(cx + R * ring * math.cos(ang(k)), cy + R * ring * math.sin(ang(k))) for k in range(7)]
        out.append(polyline(pts + [pts[0]], fill="none", stroke=GRID if ring < 1 else BORDER))
    for k in range(7):
        ex, ey = cx + R * math.cos(ang(k)), cy + R * math.sin(ang(k))
        out.append(f'<line x1="{cx}" y1="{cy}" x2="{f(ex)}" y2="{f(ey)}" stroke="{GRID}"/>')
        lx, ly = cx + (R + 16) * math.cos(ang(k)), cy + (R + 16) * math.sin(ang(k))
        out.append(text(lx, ly + 4, WEEKDAYS[k], "m", 10, "middle", ACCENT if wk[k] == mx else MUTED))
    pts = [(cx + R * (wk[k] / mx) * math.cos(ang(k)), cy + R * (wk[k] / mx) * math.sin(ang(k))) for k in range(7)]
    d = "M" + " L".join(f"{f(x)},{f(y)}" for x, y in pts) + " Z"
    out.append(f'<path class="fade" style="animation-delay:.3s" d="{d}" fill="{ACCENT}" fill-opacity=".22" stroke="{ACCENT}" stroke-width="2" filter="url(#glow)"/>')
    for x, y in pts:
        out.append(f'<circle class="fade" style="animation-delay:.6s" cx="{f(x)}" cy="{f(y)}" r="3" fill="{ACCENT}"/>')
    tot = sum(wk) or 1
    weekend = (wk[5] + wk[6]) / tot * 100
    best = max(range(7), key=lambda k: wk[k])
    stats = [("PEAK DAY", WEEKDAYS[best], f"{wk[best]/tot*100:.0f}% of volume"),
             ("WEEKEND SHARE", f"{weekend:.0f}%", "Sat + Sun"),
             ("REGULARITY", f"{a['entropy']:.2f}", "norm. Shannon H"),]
    for k, (l, v, s) in enumerate(stats):
        y = 92 + k * 64
        out.append(f'<g class="fade" style="animation-delay:{.2+k*.1:.1f}s">' + text(290, y, l, "lbl", 9.5) +
                   text(290, y + 26, v, "v", 22, fill=WHITE) + text(290, y + 42, s, "m", 9.5) + "</g>")
    return panel(W, H, "MOD-04", "Weekly Rhythm",
                 "lifetime contributions by weekday", "\n".join(out), a["generated"])


def svg_languages(a: dict) -> str:
    W, H = 445, 300
    langs = a["langs"][:8]
    other = 100 - sum(l[1] for l in langs)
    out = []
    # stacked spectrum bar
    x, x0, bwid = 22.0, 22, W - 44
    seg = []
    for name, p, _, col in langs + ([("Other", other, 0, BORDER)] if other > 0.5 else []):
        w = bwid * p / 100
        seg.append(f'<rect x="{f(x)}" y="74" width="{f(max(w-1,0))}" height="8" fill="{col}"/>')
        x += w
    out.append(f'<g class="growx"><clipPath id="sb"><rect x="{x0}" y="74" width="{bwid}" height="8" rx="4"/></clipPath><g clip-path="url(#sb)">{"".join(seg)}</g></g>')
    top = langs[0][1] if langs else 1
    for k, (name, p, nrepo, col) in enumerate(langs):
        y = 106 + k * 22.5
        bx, bmax = 150, W - 22 - 150 - 62
        out.append(f'<g class="fade" style="animation-delay:{k*.07:.2f}s">'
                   f'<circle cx="28" cy="{y-4}" r="4.5" fill="{col}"/>' + text(40, y, name, "t", 11.5) +
                   f'<rect x="{bx}" y="{y-9}" width="{bmax}" height="7" rx="3.5" fill="{GRID}"/>'
                   f'<rect class="growx" x="{bx}" y="{y-9}" width="{f(max(bmax*p/top,2))}" height="7" rx="3.5" fill="{col}"/>' +
                   text(W - 22, y, f"{p:4.1f}%", "m", 10.5, "end", TEXT) + "</g>")
    out.append(text(22, H - 16, f"repo-normalised share · {a['lang_repos']} repos analysed · {len(a['langs'])} languages detected", "m", 9))
    return panel(W, H, "MOD-05", "Language Spectrum",
                 "each repo weighted equally, split by bytes", "\n".join(out), a["generated"])


def svg_composition(a: dict) -> str:
    W, H = 445, 300
    palette = {"Commits": ACCENT, "Private work": PURPLE, "Pull requests": BLUE, "Issues": GREEN,
               "Code reviews": YELLOW, "Repos created": ACCENT2}
    items = [(k, v) for k, v in a["comp"].most_common() if v > 0]
    tot = sum(v for _, v in items) or 1
    cx, cy, r, sw = 132, 182, 72, 22
    C = 2 * math.pi * r
    out = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{GRID}" stroke-width="{sw}"/>']
    acc = 0.0
    for k, (name, v) in enumerate(items):
        frac = v / tot
        out.append(f'<circle class="fade" style="animation-delay:{k*.12:.2f}s" cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                   f'stroke="{palette.get(name, MUTED)}" stroke-width="{sw}" stroke-dasharray="{f(max(C*frac-2,0.5))} {f(C)}" '
                   f'stroke-dashoffset="{f(-C*acc)}" transform="rotate(-90 {cx} {cy})"/>')
        acc += frac
    out.append(text(cx, cy - 2, fmt_int(tot), "v", 24, "middle"))
    out.append(text(cx, cy + 16, "EVENTS", "lbl", 9, "middle"))
    for k, (name, v) in enumerate(items):
        y = 104 + k * 28
        col = palette.get(name, MUTED)
        out.append(f'<g class="fade" style="animation-delay:{.2+k*.08:.2f}s"><rect x="248" y="{y-9}" width="10" height="10" rx="2" fill="{col}"/>' +
                   text(266, y, name, "t", 11.5) + text(W - 22, y, f"{v:,}", "m", 11, "end", WHITE) +
                   text(W - 22, y + 13, f"{v/tot*100:.1f}%", "m", 9, "end") + "</g>")
    return panel(W, H, "MOD-06", "Contribution Composition",
                 "lifetime event mix by type", "\n".join(out), a["generated"])


def svg_stats(a: dict) -> str:
    W, H = 900, 300
    act = a["act365"]
    bins = [(1, 1), (2, 3), (4, 6), (7, 10), (11, 20), (21, 10**9)]
    labels = ["1", "2–3", "4–6", "7–10", "11–20", "21+"]
    hist = [sum(1 for v in act if lo <= v <= hi) for lo, hi in bins]
    x0, x1, y0, y1 = 52, 410, 92, H - 52
    ymax = nice_max(max(hist + [1]))
    bw = (x1 - x0) / len(hist)
    out = []
    for k in range(5):
        v = ymax * k / 4
        yy = y1 - v / ymax * (y1 - y0)
        out.append(f'<line x1="{x0}" y1="{f(yy)}" x2="{x1}" y2="{f(yy)}" stroke="{GRID}" stroke-dasharray="{"0" if k==0 else "3 4"}"/>')
        out.append(text(x0 - 8, yy + 4, f"{v:g}", "m", 9.5, "end"))
    bars = []
    for i, h in enumerate(hist):
        bh = h / ymax * (y1 - y0)
        bx = x0 + i * bw + bw * .14
        bars.append(f'<rect x="{f(bx)}" y="{f(y1-bh)}" width="{f(bw*.72)}" height="{f(bh)}" rx="2" fill="url(#bar)"/>')
        if h:
            out.append(text(bx + bw * .36, y1 - bh - 6, str(h), "m", 10, "middle", TEXT))
        out.append(text(bx + bw * .36, y1 + 16, labels[i], "m", 10, "middle"))
    out.append(f'<g class="grow">{"".join(bars)}</g>')
    out.append(text(x0, 80, "histogram · contributions per active day (365d)", "m", 10, fill=TEXT))
    out.append(text((x0 + x1) / 2, y1 + 36, "contributions / day", "m", 9.5, "middle"))

    metrics = [
        ("μ  mean / day", f"{a['mu']:.3f}", "all days, incl. zero"),
        ("σ  std. deviation", f"{a['sd']:.3f}", "daily dispersion"),
        ("x̃  median (active)", f"{a['median_active']:g}", "typical active day"),
        ("P90 (active)", f"{a['p90']:g}", "90th percentile"),
        ("γ  skewness", f"{a['skew']:.2f}", "right-tail heaviness"),
        ("G  Gini index", f"{a['gini']:.3f}", "0 even · 1 concentrated"),
        ("B  burstiness", f"{a['burst']:+.3f}", "Goh–Barabási, −1…+1"),
        ("ρ₁ lag-1 autocorr.", f"{a['ac1']:+.3f}", "day-to-day persistence"),
        ("H  weekday entropy", f"{a['entropy']:.3f}", "1 = perfectly uniform"),
        ("duty cycle", f"{a['active365']/365*100:.1f}%", "active days / 365"),
    ]
    mx0 = 448
    colw = (W - 22 - mx0) / 2
    for k, (name, val, hint) in enumerate(metrics):
        c, r = divmod(k, 5)
        x, y = mx0 + c * colw, 84 + r * 40
        out.append(f'<g class="fade" style="animation-delay:{k*.06:.2f}s">'
                   f'<rect x="{f(x)}" y="{y}" width="{f(colw-10)}" height="34" rx="5" fill="{TILE}" stroke="{GRID}"/>' +
                   text(x + 10, y + 15, name, "m", 10.5, fill=TEXT) + text(x + 10, y + 28, hint, "m", 8.5) +
                   text(x + colw - 20, y + 23, val, "v", 14, "end", ACCENT if k in (5, 6) else WHITE) + "</g>")
    return panel(W, H, "MOD-07 // STATISTICS", "Statistical Signature",
                 "distribution & dynamics of daily output · trailing 365 days", "\n".join(out), a["generated"])


# ═════════════════════════════════════════════════════════════════════════════
def main() -> None:
    login = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_REPOSITORY_OWNER", "flamekaizen")
    raw = fetch(login)
    raw["login"] = login
    a = analyse(raw)
    OUT.mkdir(exist_ok=True)
    panels = {
        "overview.svg": svg_overview,
        "activity.svg": svg_activity,
        "trend.svg": svg_trend,
        "fingerprint.svg": svg_fingerprint,
        "rhythm.svg": svg_radar,
        "languages.svg": svg_languages,
        "composition.svg": svg_composition,
        "statistics.svg": svg_stats,
    }
    for name, fn in panels.items():
        (OUT / name).write_text(fn(a), encoding="utf-8")
        print(f"  ✓ analytics/{name}")
    summary = {k: a[k] for k in ("total", "year_total", "active365", "last30")}
    summary.update(current=a["current"][0], longest=a["longest"][0], peak=a["peak"][0])
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
