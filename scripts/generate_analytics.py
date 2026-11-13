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
            repositoriesContributedTo(first:1,contributionTypes:[COMMIT,ISSUE,PULL_REQUEST,REPOSITORY]){totalCount}
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
    wk365 = [0] * 7
    for d, c in zip(days[-365:], last365):
        wk365[d.weekday()] += c
    wsum = sum(wk365)
    ent = -sum((v / wsum) * math.log2(v / wsum) for v in wk365 if v) / math.log2(7) if wsum else 0

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
        "fano": (sd * sd / mu) if mu else 0,
        "contributed_to": raw["head"]["repositoriesContributedTo"]["totalCount"],
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
#  Design rules — one question per panel, one meaning per colour:
#    flame red  = your raw activity        blue  = models / derived signals
#    amber      = annotations (peaks)      green = positive change only
#    greys      = structure; everything else stays out of the way.
# ═════════════════════════════════════════════════════════════════════════════
RAMP = ["#F73859", "#C92D4A", "#9B2339", "#FF8A5B", "#6E1A2A", MUTED]


def delta_color(p) -> str:
    if p is None:
        return MUTED
    return GREEN if p >= 0 else ACCENT2


def axis_grid(out, x0, x1, Y, ymax, size=10):
    for k in range(5):
        v = ymax * k / 4
        yy = Y(v)
        out.append(f'<line x1="{x0}" y1="{f(yy)}" x2="{x1}" y2="{f(yy)}" stroke="{GRID}" stroke-dasharray="{"0" if k == 0 else "3 4"}"/>')
        out.append(text(x0 - 10, yy + 4, f"{v:g}", "m", size, "end"))


def year_totals(keys, vals) -> Counter:
    t = Counter()
    for (y, _), v in zip(keys, vals):
        t[y] += v
    return t


def svg_overview(a: dict) -> str:
    """Q: How much, how consistently, how fast?  -> 4 groups x 2 KPIs."""
    W, H = 900, 262
    cur, lng = a["current"], a["longest"]
    slope, _, r2, _ = a["reg"]
    mom = a["momentum"]
    if mom is not None:
        mom_txt, mom_col = fmt_pct(mom), delta_color(mom)
    else:
        mom_txt, mom_col = ("▲ NEW", GREEN) if a["last30"] else ("—", WHITE)
    groups = [
        ("01 · VOLUME", [
            ("LIFETIME", fmt_int(a["total"]), f"since {fmt_date(a['created'])}", MUTED, None, WHITE),
            ("LAST 365 DAYS", fmt_int(a["year_total"]), f"{fmt_pct(a['yoy'])} year-over-year", delta_color(a["yoy"]), None, WHITE),
        ]),
        ("02 · CONSISTENCY", [
            ("CURRENT STREAK", f"{cur[0]} d", f"{fmt_date(cur[1], False)} → {fmt_date(cur[2], False)}" if cur[0] else "—", MUTED,
             (cur[0] / lng[0]) if lng[0] else 0, WHITE),
            ("LONGEST STREAK", f"{lng[0]} d", f"{fmt_date(lng[1], False)} → {fmt_date(lng[2])}" if lng[0] else "—", MUTED, None, WHITE),
        ]),
        ("03 · CADENCE", [
            ("ACTIVE DAYS / 365", fmt_int(a["active365"]), f"{a['active365'] / 365 * 100:.1f}% duty cycle", MUTED, a["active365"] / 365, WHITE),
            ("PEAK DAY", fmt_int(a["peak"][0]), fmt_date(a["peak"][1]), MUTED, None, YELLOW),
        ]),
        ("04 · VELOCITY", [
            ("30-DAY MOMENTUM", mom_txt, f"{a['last30']} vs prior 30 days", MUTED, None, mom_col),
            ("TREND SLOPE", f"{slope:+.1f}/mo", f"OLS · R² {r2:.2f} · 12 mo", MUTED, None, BLUE),
        ]),
    ]
    x0, gap = 20, 12
    tw = (W - 2 * x0 - 3 * gap) / 4
    th, top = 70, 92
    out = []
    for gi, (gname, tiles) in enumerate(groups):
        gx = x0 + gi * (tw + gap)
        out.append(f'<g class="fade" style="animation-delay:{gi * .1:.1f}s">' + text(gx, 82, gname, "lbl", 9.5, fill=ACCENT)
                   + f'<line x1="{f(gx + len(gname) * 7.4 + 6)}" y1="79" x2="{f(gx + tw)}" y2="79" stroke="{GRID}"/></g>')
        for ti, (lbl, val, sub, subc, prog, valc) in enumerate(tiles):
            y = top + ti * (th + 10)
            g = [f'<g class="fade" style="animation-delay:{gi * .1 + ti * .05 + .1:.2f}s">',
                 f'<rect x="{f(gx)}" y="{y}" width="{f(tw)}" height="{th}" rx="6" fill="{TILE}" stroke="{GRID}"/>',
                 f'<rect x="{f(gx)}" y="{y + 12}" width="2.5" height="16" fill="{ACCENT}"/>',
                 text(gx + 13, y + 24, lbl, "lbl", 9.5),
                 text(gx + 13, y + 50, val, "v", 22, fill=valc),
                 text(gx + 13, y + 64, sub, "m", 9.5, fill=subc)]
            if prog is not None:
                bx, bw = gx + tw - 70, 56
                g.append(f'<rect x="{f(bx)}" y="{y + 44}" width="{bw}" height="3" rx="1.5" fill="{GRID}"/>')
                g.append(f'<rect class="growx" x="{f(bx)}" y="{y + 44}" width="{f(max(bw * min(prog, 1), 2))}" height="3" rx="1.5" fill="{ACCENT}"/>')
                g.append(text(bx + bw, y + 38, f"{min(prog, 1) * 100:.0f}%", "m", 9, "end"))
            g.append("</g>")
            out.append("".join(g))
    age = (a["today"] - a["created"]).days / 365.25
    sub = (f"{a['repo_count']} repositories · {len(a['langs'])} languages · "
           f"contributed to {a['contributed_to']} external repos · {age:.1f} yrs on GitHub")
    return panel(W, H, "MOD-01 // TELEMETRY", "System Telemetry", sub, "\n".join(out), a["generated"])


def svg_signal(a: dict) -> str:
    """Q: What does my output look like over time?  Focus (365 d daily) + context (lifetime monthly)."""
    W, H = 900, 440
    N = 365
    days, counts, full = a["days"][-N:], a["counts"][-N:], a["counts"]
    off = len(full) - len(counts)
    ma7 = [statistics.fmean(full[max(0, off + i - 6): off + i + 1]) for i in range(len(counts))]
    ema, alpha, e = [], 2 / 29, None
    for v in full:
        e = v if e is None else alpha * v + (1 - alpha) * e
        ema.append(e)
    ema = ema[off:]

    # ── focus chart ──
    x0, x1, y0, y1 = 58, W - 24, 96, 286
    ymax = nice_max(max(counts + [1]))
    n = len(counts)
    bw = (x1 - x0) / n
    X = lambda i: x0 + bw * (i + .5)
    Y = lambda v: y1 - v / ymax * (y1 - y0)
    out = []
    axis_grid(out, x0, x1, Y, ymax)
    for i, d in enumerate(days):
        if d.day == 1:
            out.append(f'<line x1="{f(X(i))}" y1="{y1}" x2="{f(X(i))}" y2="{y1 + 4}" stroke="{MUTED}"/>')
            out.append(text(X(i), y1 + 17, MONTHS[d.month - 1], "m", 9.5, "middle"))
    bars = "".join(f'<rect x="{f(x0 + bw * i)}" y="{f(Y(c))}" width="{f(max(bw * .7, 1))}" height="{f(y1 - Y(c))}" fill="{ACCENT}" opacity=".32"/>'
                   for i, c in enumerate(counts) if c)
    out.append(f'<g class="grow">{bars}</g>')
    pts = [(X(i), Y(v)) for i, v in enumerate(ma7)]
    area = f"M{f(X(0))},{y1} " + " ".join(f"L{f(px)},{f(py)}" for px, py in pts) + f" L{f(X(n - 1))},{y1} Z"
    out.append(f'<path class="fade" d="{area}" fill="url(#area)"/>')
    out.append(polyline([(X(i), Y(v)) for i, v in enumerate(ema)], fill="none", stroke=BLUE, stroke_width="1.5", stroke_dasharray="5 4"))
    out.append(polyline(pts, pathLength="1", **{"class": "draw"}, fill="none", stroke=ACCENT, stroke_width="2.2",
                        stroke_linejoin="round", filter="url(#glow)"))
    pk = max(range(n), key=lambda i: counts[i])
    if counts[pk]:
        px, py = X(pk), Y(counts[pk])
        anc, dx = ("end", -12) if px > W - 200 else ("start", 12)
        out.append(f'<g class="fade" style="animation-delay:1.2s"><circle cx="{f(px)}" cy="{f(py)}" r="4" fill="{BG}" stroke="{YELLOW}" stroke-width="2"/>'
                   f'<circle class="pulse" cx="{f(px)}" cy="{f(py)}" r="9" fill="none" stroke="{YELLOW}" opacity=".6"/>'
                   + text(px + dx, py + 4, f"peak {counts[pk]} · {fmt_date(days[pk], False)}", "m", 10, anc, YELLOW) + "</g>")
    lx = x0
    for col, name, kind in ((ACCENT, "daily", "bar"), (ACCENT, "7-day mean", None), (BLUE, "28-day EMA", "5 4")):
        if kind == "bar":
            out.append(f'<rect x="{lx}" y="72" width="9" height="9" fill="{col}" opacity=".4"/>')
        else:
            out.append(f'<line x1="{lx}" y1="76.5" x2="{lx + 16}" y2="76.5" stroke="{col}" stroke-width="2" stroke-dasharray="{kind or 0}"/>')
        out.append(text(lx + 22, 80, name, "m", 10))
        lx += 22 + len(name) * 6.3 + 20
    tot, act = sum(counts), sum(1 for c in counts if c)
    out.append(text(x1, 80, f"Σ {tot} · {act} active days · EMA {ema[-1]:.2f}/day", "m", 10, "end", TEXT))

    # ── context strip: lifetime monthly ──
    keys, vals = a["mkeys"], a["mvals"]
    cx0, cx1, cy0, cy1 = x0, x1, 350, 398
    m = len(vals)
    mbw = (cx1 - cx0) / m
    MX = lambda i: cx0 + mbw * (i + .5)
    cmax = max(vals + [1])
    MY = lambda v: cy1 - v / cmax * (cy1 - cy0)
    out.append(text(22, 332, "LIFETIME · MONTHLY", "lbl", 9, fill=ACCENT))
    out.append(text(x1, 332, "  ·  ".join(f"{y}: {t}" for y, t in sorted(year_totals(keys, vals).items())), "m", 9.5, "end"))
    w0 = max(0, m - 12)
    wx0, wx1 = cx0 + mbw * w0, cx1
    out.append(f'<path d="M{x0},{y1 + 24} L{f(wx0)},{cy0 - 6} M{x1},{y1 + 24} L{f(wx1)},{cy0 - 6}" stroke="{BORDER}" stroke-dasharray="2 3" fill="none"/>')
    out.append(f'<rect x="{f(wx0)}" y="{cy0 - 6}" width="{f(wx1 - wx0)}" height="{cy1 - cy0 + 6}" fill="{ACCENT}" fill-opacity=".05" '
               f'stroke="{ACCENT}" stroke-opacity=".35" stroke-dasharray="3 3"/>')
    cb = []
    for i, ((yy, mm), v) in enumerate(zip(keys, vals)):
        if v:
            op = ".5" if i == m - 1 else (".9" if i >= w0 else ".45")
            cb.append(f'<rect x="{f(cx0 + mbw * i + mbw * .15)}" y="{f(MY(v))}" width="{f(mbw * .7)}" height="{f(cy1 - MY(v))}" rx="1" '
                      f'fill="{ACCENT if i >= w0 else MUTED}" opacity="{op}"/>')
        if mm == 1 or i == 0:
            out.append(text(cx0 + mbw * i + 3, cy1 + 15, str(yy), "m", 9.5, fill=TEXT))
            if i:
                out.append(f'<line x1="{f(cx0 + mbw * i)}" y1="{cy0 - 8}" x2="{f(cx0 + mbw * i)}" y2="{cy1 + 4}" stroke="{GRID}"/>')
    out.append(f'<line x1="{cx0}" y1="{cy1}" x2="{cx1}" y2="{cy1}" stroke="{BORDER}"/>')
    out.append(f'<g class="grow">{"".join(cb)}</g>')
    slope, icpt, r2, mreg = a["reg"]
    if mreg >= 3:
        s = m - 1 - mreg
        out.append(f'<line class="fade" style="animation-delay:1s" x1="{f(MX(s))}" y1="{f(MY(max(icpt, 0)))}" '
                   f'x2="{f(MX(s + mreg - 1))}" y2="{f(MY(max(icpt + slope * (mreg - 1), 0)))}" stroke="{BLUE}" stroke-width="1.8" stroke-dasharray="5 3"/>')
    out.append(text(22, H - 14, f"dashed blue = least-squares trend, last 12 complete months ({slope:+.1f}/mo, R² {r2:.2f})"
                    "  ·  highlighted window = focus chart above", "m", 9))
    return panel(W, H, "MOD-02 // SIGNAL", "Contribution Signal",
                 "focus: last 365 days, daily · context: entire history, monthly", "\n".join(out), a["generated"])


def svg_temporal(a: dict) -> str:
    """Q: When does the work happen?  Heatmap + weekday marginal + callouts."""
    W, H = 900, 300
    fp, keys = a["fp"], a["fp_keys"]
    flat = sorted(v for row in fp for v in row if v)

    def level(v):
        if not v or not flat:
            return 0
        q = sum(1 for t in flat if t <= v) / len(flat)
        return 1 + min(3, int(q * 4 - 1e-9))

    x0, y0, ch = 58, 80, 24
    cw = 520 / max(len(keys), 1)
    out = []
    for r in range(7):
        out.append(text(x0 - 10, y0 + r * ch + 16, WEEKDAYS[r], "m", 10, "end"))
        for c in range(len(keys)):
            v = fp[r][c]
            out.append(f'<rect class="fade" style="animation-delay:{(r + c) * .025:.2f}s" x="{f(x0 + c * cw + 1.5)}" y="{y0 + r * ch + 1.5}" '
                       f'width="{f(cw - 3)}" height="{ch - 3}" rx="3" fill="{HEAT[level(v)]}"><title>{WEEKDAYS[r]} · '
                       f'{MONTHS[keys[c][1] - 1]} {keys[c][0]}: {v}</title></rect>')
    for c, (yy, mm) in enumerate(keys):
        lab = MONTHS[mm - 1] if mm != 1 else f"Jan '{yy % 100:02d}"
        out.append(text(x0 + c * cw + cw / 2, y0 + 7 * ch + 15, lab, "m", 9, "middle", TEXT if mm == 1 else MUTED))
    ly = H - 22
    out.append(text(x0, ly + 9, "less", "m", 9))
    for k, col in enumerate(HEAT):
        out.append(f'<rect x="{x0 + 28 + k * 14}" y="{ly}" width="11" height="11" rx="2" fill="{col}"/>')
    out.append(text(x0 + 28 + 5 * 14 + 4, ly + 9, "more  · quartile-scaled", "m", 9))

    # weekday marginal (same 12-month window)
    wk = [sum(row) for row in fp]
    tot = sum(wk) or 1
    best = max(range(7), key=lambda k: wk[k])
    mx0, mw = x0 + 520 + 26, 110
    out.append(text(mx0, y0 - 6, "SHARE BY WEEKDAY", "lbl", 8.5))
    for r in range(7):
        y = y0 + r * ch + 6
        w = mw * wk[r] / max(wk + [1])
        out.append(f'<rect x="{mx0}" y="{y}" width="{mw}" height="10" rx="2" fill="{GRID}"/>')
        out.append(f'<rect class="growx" x="{mx0}" y="{y}" width="{f(max(w, 1.5))}" height="10" rx="2" fill="{ACCENT}" opacity="{1 if r == best else .5}"/>')
        out.append(text(mx0 + mw + 8, y + 9, f"{wk[r] / tot * 100:.1f}%", "m", 9.5, fill=TEXT if r == best else MUTED))

    cx = W - 22
    hot = max(((r, c) for r in range(7) for c in range(len(keys))), key=lambda rc: fp[rc[0]][rc[1]])
    weekend = (wk[5] + wk[6]) / tot * 100
    calls = [("PEAK WEEKDAY", WEEKDAYS[best], f"{wk[best] / tot * 100:.0f}% of output"),
             ("WEEKEND SHARE", f"{weekend:.0f}%", "uniform = 28.6%"),
             ("HOTTEST CELL", f"{fp[hot[0]][hot[1]]}", f"{WEEKDAYS[hot[0]]}s · {MONTHS[keys[hot[1]][1] - 1]} '{keys[hot[1]][0] % 100:02d}")]
    for k, (l, v, s) in enumerate(calls):
        y = y0 + 4 + k * 58
        out.append(f'<g class="fade" style="animation-delay:{.3 + k * .1:.1f}s">' + text(cx, y, l, "lbl", 8.5, "end")
                   + text(cx, y + 24, v, "v", 20, "end", WHITE) + text(cx, y + 38, s, "m", 9, "end") + "</g>")
    return panel(W, H, "MOD-03 // RHYTHM", "Temporal Fingerprint",
                 "when the work happens · weekday × month, last 12 months", "\n".join(out), a["generated"])


def svg_dna(a: dict) -> str:
    """Q: What is the output made of?  Languages + contribution-type mix."""
    W, H = 900, 306
    out = []
    L0, L1 = 22, 500
    langs = a["langs"][:8]
    other = max(0.0, 100 - sum(l[1] for l in langs))
    out.append(text(L0, 82, "LANGUAGE SPECTRUM", "lbl", 9, fill=ACCENT))
    x, seg = float(L0), []
    for name, p, _, col in langs + ([("Other", other, 0, BORDER)] if other > .5 else []):
        w = (L1 - L0) * p / 100
        seg.append(f'<rect x="{f(x)}" y="92" width="{f(max(w - 1.5, 0))}" height="6" fill="{col}"/>')
        x += w
    out.append(f'<clipPath id="sb"><rect x="{L0}" y="92" width="{L1 - L0}" height="6" rx="3"/></clipPath>'
               f'<g class="growx"><g clip-path="url(#sb)">{"".join(seg)}</g></g>')
    top = langs[0][1] if langs else 1
    for k, (name, p, nrepo, col) in enumerate(langs):
        y = 126 + k * 19.5
        bx, bmax = L0 + 140, L1 - L0 - 140 - 52
        out.append(f'<g class="fade" style="animation-delay:{k * .06:.2f}s"><circle cx="{L0 + 5}" cy="{y - 4}" r="4" fill="{col}"/>'
                   + text(L0 + 16, y, name, "t", 11.5)
                   + f'<rect x="{bx}" y="{y - 8}" width="{bmax}" height="5" rx="2.5" fill="{GRID}"/>'
                   f'<rect class="growx" x="{bx}" y="{y - 8}" width="{f(max(bmax * p / top, 2))}" height="5" rx="2.5" fill="{ACCENT}" opacity="{1 - k * .07:.2f}"/>'
                   + text(L1, y, f"{p:.1f}%", "m", 10.5, "end", TEXT) + "</g>")
    out.append(text(L0, H - 16, f"repo-normalised · {a['lang_repos']} repos · {len(a['langs'])} languages detected", "m", 9))

    out.append(f'<line x1="525" y1="76" x2="525" y2="{H - 22}" stroke="{GRID}"/>')

    R0, R1 = 550, W - 22
    items = [(k, v) for k, v in a["comp"].most_common() if v > 0]
    tot = sum(v for _, v in items) or 1
    out.append(text(R0, 82, "CONTRIBUTION MIX", "lbl", 9, fill=ACCENT))
    x, seg = float(R0), []
    for k, (name, v) in enumerate(items):
        w = (R1 - R0) * v / tot
        seg.append(f'<rect x="{f(x)}" y="92" width="{f(max(w - 1.5, .8))}" height="6" fill="{RAMP[min(k, len(RAMP) - 1)]}"/>')
        x += w
    out.append(f'<clipPath id="cb"><rect x="{R0}" y="92" width="{R1 - R0}" height="6" rx="3"/></clipPath>'
               f'<g class="growx"><g clip-path="url(#cb)">{"".join(seg)}</g></g>')
    for k, (name, v) in enumerate(items):
        y = 126 + k * 26
        out.append(f'<g class="fade" style="animation-delay:{.2 + k * .07:.2f}s">'
                   f'<rect x="{R0}" y="{y - 9}" width="10" height="10" rx="2" fill="{RAMP[min(k, len(RAMP) - 1)]}"/>'
                   + text(R0 + 18, y, name, "t", 11.5) + text(R1 - 56, y, f"{v:,}", "v", 12, "end")
                   + text(R1, y, f"{v / tot * 100:.1f}%", "m", 10.5, "end") + "</g>")
    out.append(text(R0, H - 16, f"lifetime · {tot:,} events by type", "m", 9))
    return panel(W, H, "MOD-04 // COMPOSITION", "Output DNA",
                 "what the work is made of · languages & contribution types", "\n".join(out), a["generated"])


def svg_stats(a: dict) -> str:
    """Q: What is the statistical character of my output?"""
    W, H = 900, 300
    act = a["act365"]
    bins = [(1, 1), (2, 3), (4, 6), (7, 10), (11, 20), (21, 10 ** 9)]
    labels = ["1", "2–3", "4–6", "7–10", "11–20", "21+"]
    hist = [sum(1 for v in act if lo <= v <= hi) for lo, hi in bins]
    x0, x1, y0, y1 = 52, 410, 92, H - 52
    ymax = nice_max(max(hist + [1]))
    bw = (x1 - x0) / len(hist)
    out = []
    axis_grid(out, x0, x1, lambda v: y1 - v / ymax * (y1 - y0), ymax, size=9.5)
    bars = []
    for i, h in enumerate(hist):
        bh = h / ymax * (y1 - y0)
        bx = x0 + i * bw + bw * .14
        bars.append(f'<rect x="{f(bx)}" y="{f(y1 - bh)}" width="{f(bw * .72)}" height="{f(bh)}" rx="2" fill="url(#bar)"/>')
        if h:
            out.append(text(bx + bw * .36, y1 - bh - 6, str(h), "m", 10, "middle", TEXT))
        out.append(text(bx + bw * .36, y1 + 16, labels[i], "m", 10, "middle"))
    out.append(f'<g class="grow">{"".join(bars)}</g>')
    out.append(text(22, 80, "CONTRIBUTIONS PER ACTIVE DAY", "lbl", 9, fill=ACCENT))
    out.append(text((x0 + x1) / 2, y1 + 34, "contributions / day  →  number of active days", "m", 9.5, "middle"))
    metrics = [
        ("μ  mean / day", f"{a['mu']:.3f}", "all days incl. zero"),
        ("σ  std. deviation", f"{a['sd']:.3f}", "daily dispersion"),
        ("x̃  median (active)", f"{a['median_active']:g}", "typical active day"),
        ("P90 (active)", f"{a['p90']:g}", "90th percentile"),
        ("γ  skewness", f"{a['skew']:.2f}", "right-tail heaviness"),
        ("F  Fano factor", f"{a['fano']:.2f}", "σ²/μ · 1 = Poisson"),
        ("G  Gini index", f"{a['gini']:.3f}", "0 even · 1 concentrated"),
        ("B  burstiness", f"{a['burst']:+.3f}", "Goh–Barabási −1…+1"),
        ("ρ₁ lag-1 autocorr.", f"{a['ac1']:+.3f}", "day-to-day persistence"),
        ("H  weekday entropy", f"{a['entropy']:.3f}", "1 = uniform week"),
    ]
    mx0 = 448
    colw = (W - 22 - mx0) / 2
    for k, (name, val, hint) in enumerate(metrics):
        c, r = divmod(k, 5)
        x, y = mx0 + c * colw, 70 + r * 42
        out.append(f'<g class="fade" style="animation-delay:{k * .05:.2f}s">'
                   f'<rect x="{f(x)}" y="{y}" width="{f(colw - 10)}" height="36" rx="5" fill="{TILE}" stroke="{GRID}"/>'
                   + text(x + 10, y + 16, name, "m", 10.5, fill=TEXT) + text(x + 10, y + 29, hint, "m", 8.5)
                   + text(x + colw - 20, y + 24, val, "v", 14, "end", WHITE) + "</g>")
    return panel(W, H, "MOD-05 // STATISTICS", "Statistical Signature",
                 "distribution & dynamics of daily output · trailing 365 days", "\n".join(out), a["generated"])


def svg_divider() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="14" viewBox="0 0 900 14">
<defs><linearGradient id="d" x1="0" x2="1"><stop offset="0" stop-color="{ACCENT}" stop-opacity="0"/><stop offset=".35" stop-color="{ACCENT}"/>
<stop offset=".65" stop-color="{ACCENT2}"/><stop offset="1" stop-color="{ACCENT2}" stop-opacity="0"/></linearGradient></defs>
<rect x="0" y="6.5" width="900" height="1" fill="url(#d)"/>
<rect x="444" y="2" width="9" height="9" transform="rotate(45 448.5 6.5)" fill="{BG}" stroke="{ACCENT}" stroke-width="1.5"/>
<circle cx="448.5" cy="6.5" r="1.6" fill="{ACCENT}"/>
</svg>
"""


# ═════════════════════════════════════════════════════════════════════════════
def main() -> None:
    login = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_REPOSITORY_OWNER", "flamekaizen")
    raw = fetch(login)
    raw["login"] = login
    a = analyse(raw)
    OUT.mkdir(exist_ok=True)
    panels = {
        "overview.svg": svg_overview,
        "signal.svg": svg_signal,
        "temporal.svg": svg_temporal,
        "dna.svg": svg_dna,
        "statistics.svg": svg_stats,
    }
    for name, fn in panels.items():
        (OUT / name).write_text(fn(a), encoding="utf-8")
        print(f"  ✓ analytics/{name}")
    (OUT / "divider.svg").write_text(svg_divider(), encoding="utf-8")
    keep = set(panels) | {"divider.svg"}
    for stale in OUT.glob("*.svg"):
        if stale.name not in keep:
            stale.unlink()
            print(f"  ✗ removed stale analytics/{stale.name}")
    print(json.dumps({k: a[k] for k in ("total", "year_total", "active365", "last30", "contributed_to")}))


if __name__ == "__main__":
    main()
