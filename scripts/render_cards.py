#!/usr/bin/env python3
"""One renderer for Aqeel's GitHub profile. Python 3.11+, FontTools/pyftsubset.

Default: read profile.json + data/contributions.json, render cards/ + README.md.
--refresh --data-only: fetch the GitHub GraphQL calendar using GH_TOKEN.
--import-calendar FILE --as-of YYYY-MM-DD: bootstrap from public GitHub HTML.
STATIC=1: final frames in preview/cards/ and preview/README.md (never cards/).
"""
from __future__ import annotations

import argparse
import base64
import calendar
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import string
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
W = 960
SVG_NS = "http://www.w3.org/2000/svg"


def esc(value):
    return html.escape(str(value), quote=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def window_start(end):
    """Twelve calendar months, including the current partial month."""
    first = end.replace(day=1)
    for _ in range(11):
        first = (first - timedelta(days=1)).replace(day=1)
    return first


def validate_data(data, username):
    if data.get("username", "").lower() != username.lower():
        raise ValueError("Contribution data belongs to another username")
    start, end = date.fromisoformat(data["from"]), date.fromisoformat(data["as_of"])
    if start != window_start(end):
        raise ValueError("Expected twelve calendar months including the current month")
    days = data["days"]
    expected = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
    if [d["date"] for d in days] != expected:
        raise ValueError("Calendar must be sorted, complete, unique, and end at as_of")
    if any(type(d["count"]) is not int or d["count"] < 0 for d in days):
        raise ValueError("Contribution counts must be nonnegative integers")
    return data


class CalendarParser(HTMLParser):
    """Exact counts come from tooltips; intensity levels are never used as counts."""
    def __init__(self):
        super().__init__()
        self.cells, self.counts = {}, {}
        self.tooltip, self.parts = None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "td" and a.get("data-date"):
            self.cells[a["id"]] = a["data-date"]
        if tag == "tool-tip" and a.get("for", "").startswith("contribution-day-"):
            self.tooltip, self.parts = a["for"], []

    def handle_data(self, text):
        if self.tooltip:
            self.parts.append(text)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self.tooltip:
            text = "".join(self.parts).strip()
            match = re.match(r"(No|[\d,]+) contributions? on ", text)
            if not match:
                raise ValueError(f"Unrecognized GitHub tooltip: {text!r}")
            self.counts[self.tooltip] = 0 if match[1] == "No" else int(match[1].replace(",", ""))
            self.tooltip = None


def import_calendar(path, username, end):
    parser = CalendarParser()
    parser.feed(path.read_text(encoding="utf-8"))
    start = window_start(end)
    days = sorted([
        {"date": day, "count": parser.counts[cell]}
        for cell, day in parser.cells.items()
        if start.isoformat() <= day <= end.isoformat() and cell in parser.counts
    ], key=lambda d: d["date"])
    return validate_data({"schema_version": 1, "username": username,
        "from": start.isoformat(), "as_of": end.isoformat(), "timezone": "UTC",
        "source": f"https://github.com/users/{username}/contributions",
        "scope": "Public GitHub contribution calendar", "days": days}, username)


def refresh(username, end):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("Set GH_TOKEN (GitHub Actions supplies github.token); never put tokens in files")
    start = window_start(end)
    query = """query($login:String!, $from:DateTime!, $to:DateTime!) {
      user(login:$login) { contributionsCollection(from:$from,to:$to) {
        contributionCalendar { weeks { contributionDays { date contributionCount } } }
      } }
    }"""
    variables = {"login": username, "from": f"{start}T00:00:00Z", "to": f"{end}T23:59:59Z"}
    req = Request("https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": f"{username}-profile-cards", "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=60) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise ValueError("GitHub GraphQL: " + "; ".join(e["message"] for e in payload["errors"]))
    user = payload.get("data", {}).get("user")
    if not user:
        raise ValueError("GitHub user not found")
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = sorted([{"date": d["date"], "count": d["contributionCount"]}
        for w in weeks for d in w["contributionDays"]
        if start.isoformat() <= d["date"] <= end.isoformat()], key=lambda d: d["date"])
    return validate_data({"schema_version": 1, "username": username,
        "from": start.isoformat(), "as_of": end.isoformat(), "timezone": "UTC",
        "source": "https://api.github.com/graphql",
        "scope": "GitHub contribution calendar visible to the workflow token", "days": days}, username)


def statistics(data):
    days = data["days"]
    monthly = {}
    longest = run = 0
    for d in days:
        key = d["date"][:7]
        monthly[key] = monthly.get(key, 0) + d["count"]
        run = run + 1 if d["count"] else 0
        longest = max(longest, run)
    # Today may still be in progress: allow yesterday to anchor the current streak.
    cursor = len(days) - 1
    if days[cursor]["count"] == 0:
        cursor -= 1
    current = 0
    while cursor >= 0 and days[cursor]["count"]:
        current += 1
        cursor -= 1
    total = sum(d["count"] for d in days)
    return {"monthly": monthly, "total": total, "active": sum(d["count"] > 0 for d in days),
            "longest": longest, "current": current,
            "busiest": max(days, key=lambda d: (d["count"], d["date"])) if total else None}


def subset_fonts(profile):
    # These arguments call the same entry point as the pyftsubset executable.
    chars = "".join(sorted(set(string.printable[:95] + json.dumps(profile, ensure_ascii=False)
                               + " ·–—→’°")))
    cache = ROOT / ".font-cache"
    cache.mkdir(exist_ok=True)
    result = {}
    for family, source in [("Brand", "SpaceGrotesk.ttf"), ("Mono", "JetBrainsMono.ttf")]:
        source = ROOT / "assets" / "fonts" / source
        digest = hashlib.sha256(source.read_bytes() + chars.encode()).hexdigest()[:16]
        target = cache / f"{family}-{digest}.woff"
        if not target.exists():
            command = [sys.executable, "-m", "fontTools.subset", str(source),
                       f"--text={chars}", "--flavor=woff", f"--output-file={target}",
                       "--no-hinting", "--layout-features=*"]
            process = subprocess.run(command, capture_output=True, text=True)
            if process.returncode:
                raise RuntimeError("pyftsubset failed. Install requirements.txt.\n" + process.stderr)
        result[family] = base64.b64encode(target.read_bytes()).decode()
    return result


class Renderer:
    def __init__(self, profile, data, out, static=False):
        self.p, self.data, self.out, self.static = profile, data, out, static
        self.c = profile["brand"]
        self.fonts = subset_fonts(profile)
        self.out.mkdir(parents=True, exist_ok=True)
        self.files = []

    def text(self, x, y, content, size=18, fill=None, weight=400, mono=False, extra=""):
        return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
                f'fill="{fill or self.c["text"]}" font-family="{("Mono" if mono else "Brand")}, sans-serif" '
                f'{extra}>{esc(content)}</text>')

    def label(self, x, y, content, fill=None, size=12):
        return self.text(x, y, content, size, fill or self.c["muted"], 400, True,
                         'letter-spacing="1.6"')

    def group(self, content, delay):
        return f'<g class="enter" style="animation-delay:{delay:.2f}s">{content}</g>'

    def icon(self, kind, x, y, scale=1):
        paths = {
            "figma": '<rect x="7" y="2" width="10" height="10" rx="5"/><rect x="17" y="2" width="10" height="10" rx="5"/><rect x="7" y="12" width="10" height="10" rx="5"/><circle cx="22" cy="17" r="5"/><path d="M7 27a5 5 0 0 0 10 0v-5h-5a5 5 0 0 0-5 5Z"/>',
            "linkedin": '<rect x="3" y="3" width="28" height="28" rx="5"/><path d="M10 15v11m0-17v1m7 16V15m0 5c0-7 9-7 9 0v6"/>',
            "links": '<path d="m14 11 4-4a8 8 0 0 1 11 11l-4 4M20 23l-4 4A8 8 0 0 1 5 16l4-4m2 11 12-12"/>',
            "layers": '<path d="m17 3 15 8-15 8L2 11 17 3Zm-15 15 15 8 15-8M2 25l15 8 15-8"/>',
            "orbit": '<circle cx="17" cy="17" r="4"/><ellipse cx="17" cy="17" rx="17" ry="8" transform="rotate(-35 17 17)"/><path d="M10 3a17 17 0 0 1 14 28"/>',
            "compass": '<circle cx="17" cy="17" r="15"/><path d="m23 11-4 12-8-8 12-4Z"/>',
        }
        return (f'<g transform="translate({x} {y}) scale({scale})" fill="none" '
                f'stroke="{self.c["accent"]}" stroke-width="1.7" stroke-linejoin="round" '
                f'stroke-linecap="round">{paths[kind]}</g>')

    def arrow(self, x, y):
        return f'<path d="M{x} {y+12}l12-12m-12 0h12v12" stroke="{self.c["accent"]}" stroke-width="2" fill="none"/>'

    def card(self, filename, height, title, description, content, width=W):
        fonts = "".join(f"@font-face{{font-family:{f};src:url(data:font/woff;base64,{v}) format('woff');font-weight:100 900;font-style:normal;}}" for f, v in self.fonts.items())
        motion = "" if self.static else """
          @keyframes enter {from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
          @keyframes grow {from{transform:scaleY(0)}to{transform:none}}
          .enter{animation:enter .65s cubic-bezier(.2,.65,.3,1) backwards}
          .bar{transform-box:fill-box;transform-origin:center bottom;animation:grow .8s cubic-bezier(.2,.65,.3,1) backwards}
          .smil-still{display:none}
          @media (prefers-reduced-motion:reduce){
            *,*::before,*::after{animation:none!important;transition:none!important}
            .enter,.bar{opacity:1!important;transform:none!important}
            .smil-motion{display:none!important}.smil-still{display:inline!important}
          }
        """
        doc = f'''<svg xmlns="{SVG_NS}" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{esc(title)}</title><desc id="desc">{esc(description)}</desc>
<defs><linearGradient id="wash" x2="1" y2="1"><stop stop-color="{self.c['surface']}"/><stop offset="1" stop-color="{self.c['background']}"/></linearGradient></defs>
<style>{fonts}{motion}</style>
<rect x=".5" y=".5" width="{width-1}" height="{height-1}" rx="20" fill="url(#wash)" stroke="{self.c['border']}"/>
{content}
</svg>'''
        ET.fromstring(doc)
        (self.out / filename).write_text(doc + "\n", encoding="utf-8")
        self.files.append(filename)

    def hero(self):
        c = self.c
        intro = self.label(36, 43, "AQEEL-ALI / MOBILE DEVELOPER", c["accent"])
        name_parts = self.p["name"].rsplit(" ", 1)
        intro += self.text(36, 115, name_parts[0], 62, weight=700)
        if len(name_parts) > 1:
            intro += self.text(36, 177, name_parts[1] + ".", 62, weight=700)
        intro += self.text(36, 228, self.p["tagline"], 17, c["muted"])
        intro += self.label(36, 299, "FLUTTER  /  KOTLIN  /  FIGMA", size=12)
        intro += self.label(36, 331, self.p["location"].upper(), c["mint"], 11)
        # Original vector illustration: a phone interface and Flutter-shaped mark.
        art = f'''<path d="M585 65h317M585 115h317M585 165h317M585 215h317M585 265h317M625 35v285M675 35v285M725 35v285M775 35v285M825 35v285M875 35v285" stroke="{c['border']}" opacity=".45"/>
        <circle cx="751" cy="176" r="113" fill="{c['accent']}" opacity=".055"/>
        <g transform="translate(680 49) rotate(9 78 123)">
          <rect width="155" height="250" rx="25" fill="{c['background']}" stroke="{c['accent']}" stroke-opacity=".6"/>
          <rect x="48" y="12" width="60" height="5" rx="2.5" fill="{c['border']}"/>
          <rect x="14" y="35" width="127" height="110" rx="14" fill="{c['surface']}"/>
          <path d="m48 94 47-47h24L60 106Zm24 24 24-24h23l-24 24 24 24H96Z" fill="{c['accent']}"/>
          <rect x="17" y="162" width="76" height="6" rx="3" fill="{c['text']}" opacity=".8"/>
          <rect x="17" y="178" width="112" height="5" rx="2.5" fill="{c['muted']}" opacity=".4"/>
          <rect x="17" y="201" width="120" height="29" rx="8" fill="{c['accent']}"/>
          <path d="M68 216h19m-5-5 5 5-5 5" stroke="{c['background']}" fill="none" stroke-width="2"/>
        </g>
        <rect x="610" y="221" width="101" height="56" rx="12" fill="{c['surface']}" stroke="{c['border']}"/>
        <path d="m625 249 9 9 17-18" fill="none" stroke="{c['mint']}" stroke-width="3"/>
        {self.label(664, 252, 'UI/UX', c['text'], 10)}
        <circle cx="858" cy="74" r="25" fill="{c['surface']}" stroke="{c['border']}"/>
        <path d="m846 74 8 8 15-16" fill="none" stroke="{c['mint']}" stroke-width="2"/>'''
        halo = f'<circle cx="751" cy="176" r="134" fill="none" stroke="{c["accent"]}" stroke-opacity=".25" stroke-dasharray="5 9"/>'
        if self.static:
            art += halo
        else:
            animated = halo.replace('/>', '><animate attributeName="stroke-dashoffset" from="90" to="0" begin="0.25s" dur="1.1s" fill="freeze"/></circle>')
            art += f'<g class="smil-motion">{animated}</g><g class="smil-still">{halo}</g>'
        portrait = self.p.get("portrait")
        if portrait:
            portrait_path = (ROOT / portrait).resolve()
            if ROOT not in portrait_path.parents:
                raise ValueError("Portrait must be inside this repository")
            ext = portrait_path.suffix.lower()
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext)
            if not mime:
                raise ValueError("Portrait must be PNG or JPEG")
            encoded = base64.b64encode(portrait_path.read_bytes()).decode()
            art = f'<defs><clipPath id="portrait"><circle cx="754" cy="172" r="112"/></clipPath></defs><image href="data:{mime};base64,{encoded}" x="642" y="60" width="224" height="224" preserveAspectRatio="xMidYMid slice" clip-path="url(#portrait)"/>' + halo
        self.card("hero.svg", 365, self.p["name"], self.p["tagline"] + " " + self.p["location"],
                  self.group(intro, .05) + self.group(art, .25))

    def links(self):
        for i, link in enumerate(self.p["links"]):
            body = self.icon(link["icon"], 23, 23, .8) + self.arrow(271, 29)
            body += self.text(23, 91, link["name"], 27, weight=600)
            body += self.text(23, 120, link["label"], 14, self.c["muted"])
            self.card(f"link-{i+1}.svg", 148, link["name"], link["label"], self.group(body, .6 + i*.12), 312)

    def activity(self):
        c, data = self.c, self.data
        s = statistics(data)
        body = self.label(34, 39, "01 / BUILDING CONSISTENTLY", c["accent"])
        body += self.text(34, 78, "A year in contributions", 32, weight=600)
        body += self.text(926, 76, str(s["total"]), 36, c["mint"], 600, extra='text-anchor="end"')
        body += self.label(926, 99, "TOTAL", size=10).replace('letter-spacing="1.6"', 'letter-spacing="1.6" text-anchor="end"')
        monthly = list(s["monthly"].items())
        maximum = max(1, max(v for _, v in monthly))
        plot_x, plot_top, base, plot_w = 55, 136, 256, 850
        for fraction in [0, .5, 1]:
            y = base - 120 * fraction
            body += f'<path d="M{plot_x} {y}H{plot_x+plot_w}" stroke="{c["border"]}" stroke-dasharray="3 6"/>'
        for i, (month, value) in enumerate(monthly):
            x = plot_x + i * (plot_w/12) + 13
            h = 120 * value / maximum
            if value:
                body += f'<rect class="bar" x="{x:.1f}" y="{base-h:.1f}" width="39" height="{h:.1f}" rx="5" fill="{c["accent"]}" style="animation-delay:{1.15+i*.045:.3f}s"><title>{esc(month)}: {value} contributions</title></rect>'
            else:
                body += f'<rect x="{x:.1f}" y="{base-2}" width="39" height="2" rx="1" fill="{c["border"]}"/>'
            body += self.text(round(x+19.5, 1), max(plot_top-9, base-h-10), value, 12, c["muted"], mono=True, extra='text-anchor="middle"')
            body += self.text(round(x+19.5, 1), 280, calendar.month_abbr[int(month[-2:])], 12, c["muted"], mono=True, extra='text-anchor="middle"')
        body += f'<path d="M34 303H926" stroke="{c["border"]}"/>'
        busiest = s["busiest"]
        busy_day = date.fromisoformat(busiest["date"]).strftime("%d %b") if busiest else "None"
        current_label = f"{s['current']} " + ("day" if s['current'] == 1 else "days")
        longest_label = f"{s['longest']} " + ("day" if s['longest'] == 1 else "days")
        stats = [("CURRENT STREAK", current_label), ("LONGEST STREAK", longest_label),
                 ("ACTIVE DAYS", str(s["active"])), ("BUSIEST DAY", busy_day)]
        for i, (label, value) in enumerate(stats):
            x = 34 + i*225
            body += self.label(x, 329, label, size=10)
            body += self.text(x, 361, value, 25, weight=600)
        note = f"{data['from']} — {data['as_of']} UTC · Current month in progress"
        body += self.text(34, 397, note, 12, c["muted"], mono=True)
        if busiest:
            peak_label = f"Peak: {busiest['count']} " + ("contribution" if busiest['count'] == 1 else "contributions")
            body += self.text(926, 397, peak_label, 12, c["muted"], mono=True, extra='text-anchor="end"')
        desc = f"{s['total']} contributions; {s['active']} active days; current streak {s['current']} days; longest streak {s['longest']} days. "
        desc += (f"Busiest day {busiest['date']}, {busiest['count']} contributions. " if busiest else "No contributions. ")
        desc += "; ".join(f"{m}: {v}" for m, v in monthly)
        self.card("activity.svg", 423, "GitHub contribution activity", desc, self.group(body, 1.0))

    def featured(self):
        c = self.c
        for i, repo in enumerate(self.p["featured"]):
            body = self.label(34, 33, f"0{i+2} / SELECTED REPOSITORY", c["accent"], 10)
            body += f'<rect x="34" y="57" width="64" height="64" rx="15" fill="{c["accent"]}" fill-opacity=".08" stroke="{c["border"]}"/>'
            body += self.icon(repo.get("icon", "layers"), 49, 72)
            body += self.label(121, 69, repo["category"], size=10)
            body += self.text(121, 105, repo["title"], 31, weight=600)
            body += self.text(121, 136, repo["description"], 17, c["muted"])
            body += self.arrow(900, 78)
            body += self.label(34, 174, f"GITHUB.COM/{self.p['username']}/{repo['repo']}".upper(), size=10)
            body += self.text(926, 174, repo["language"], 12, c["mint"], mono=True, extra='text-anchor="end"')
            self.card(f"repo-{repo['repo']}.svg", 199, repo["title"], repo["description"], self.group(body, 1.85+i*.35))

    def graph(self):
        c, days = self.c, self.data["days"]
        start = date.fromisoformat(days[0]["date"])
        sunday = start - timedelta(days=(start.weekday()+1)%7)
        last = date.fromisoformat(days[-1]["date"])
        columns = (last-sunday).days//7 + 1
        size, gap = 12, 4
        step = min(16, 850/columns)
        left, top = 68, 121
        shades = [c["border"], "#203E62", "#2D5E96", "#3C7FC5", c["accent"]]
        maximum = max(1, max(d["count"] for d in days))
        body = self.label(34, 38, f"{len(self.p['featured'])+2:02d} / SMALL STEPS, REAL PROGRESS", c["accent"])
        body += self.text(34, 77, "The contribution garden", 30, weight=600)
        month_seen = set()
        for d in days:
            when = date.fromisoformat(d["date"])
            col, row = (when-sunday).days//7, (when.weekday()+1)%7
            month = when.strftime("%Y-%m")
            if month not in month_seen:
                body += self.text(left+col*step, 108, when.strftime("%b"), 10, c["muted"], mono=True)
                month_seen.add(month)
            level = 0 if d["count"] == 0 else min(4, max(1, int((d["count"]/maximum)*3)+1))
            body += f'<rect x="{left+col*step:.2f}" y="{top+row*(size+gap)}" width="{size}" height="{size}" rx="2.5" fill="{shades[level]}"><title>{d["date"]}: {d["count"]} contributions</title></rect>'
        for row, label in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
            body += self.text(34, top+row*16+10, label, 10, c["muted"], mono=True)
        body += self.text(34, 269, f"Updated {self.data['as_of']} · UTC · GitHub contributions", 11, c["muted"], mono=True)
        body += self.text(750, 269, "Less", 11, c["muted"], mono=True)
        for i, shade in enumerate(shades):
            body += f'<rect x="{790+i*18}" y="258" width="12" height="12" rx="2" fill="{shade}"/>'
        body += self.text(886, 269, "More", 11, c["muted"], mono=True)
        self.card("contributions.svg", 293, "Contribution graph", "Daily GitHub contributions from " + self.data["from"] + " to " + self.data["as_of"] + ". Higher activity uses brighter brand blue.", self.group(body, 3.1))

    def readme(self, destination):
        username = self.p["username"]
        # Put links on the HTML anchors: anchors inside an SVG image do not work.
        lines = ["<!-- Generated by scripts/render_cards.py. Edit profile.json, then render. -->", "",
                 f'<p align="center"><img src="cards/hero.svg" width="100%" alt="{esc(self.p["name"] + ": " + self.p["tagline"])}" /></p>', "", '<p align="center">']
        for i, link in enumerate(self.p["links"]):
            lines.append(f'  <a href="{esc(link["url"])}"><img src="cards/link-{i+1}.svg" width="32.5%" alt="{esc(link["name"] + " — " + link["label"])}" /></a>')
        lines += ["</p>", "", '<p><img src="cards/activity.svg" width="100%" alt="Monthly GitHub contributions, current and longest streak, active days, and busiest day" /></p>', ""]
        for repo in self.p["featured"]:
            lines += [f'<p><a href="https://github.com/{esc(username)}/{esc(repo["repo"])}"><img src="cards/repo-{esc(repo["repo"])}.svg" width="100%" alt="{esc(repo["title"] + ": " + repo["description"])}" /></a></p>', ""]
        lines += [f'<p><a href="https://github.com/{esc(username)}?tab=overview"><img src="cards/contributions.svg" width="100%" alt="Daily contribution graph in brand blue" /></a></p>', "",
                  '<p align="center">Flutter · Dart · Kotlin · BLoC · GetX · Figma<br/>',
                  '<a href="mailto:dev.aqeelali@gmail.com">Let’s build something useful.</a></p>', ""]
        destination.write_text("\n".join(lines), encoding="utf-8")

    def run(self):
        self.hero()
        self.links()
        self.activity()
        self.featured()
        self.graph()
        self.readme(self.out.parent / "README.md")
        # Only remove files listed in the prior renderer manifest, never user files.
        manifest = self.out / "manifest.json"
        if manifest.exists():
            for old in read_json(manifest).get("files", []):
                if old not in self.files and re.fullmatch(r"[A-Za-z0-9_.-]+\.svg", old):
                    (self.out / old).unlink(missing_ok=True)
        atomic_json(manifest, {"static": self.static, "files": self.files})
        return self.files


def preview_html(profile, files, path, prefix):
    def img(name, alt=""):
        return f'<img src="{prefix}/{esc(name)}" alt="{esc(alt or name)}">'
    items = [img("hero.svg", profile["name"]), '<nav>']
    for i, link in enumerate(profile["links"]):
        items.append(f'<a href="{esc(link["url"])}">' + img(f"link-{i+1}.svg", link["name"]) + '</a>')
    items += ['</nav>', img('activity.svg', 'Contribution activity')]
    for repo in profile["featured"]:
        items.append(f'<a href="https://github.com/{esc(profile["username"])}/{esc(repo["repo"])}">' + img(f"repo-{repo['repo']}.svg", repo["title"]) + '</a>')
    items.append(img('contributions.svg', 'Contribution graph'))
    path.write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Aqeel Ali — GitHub profile preview</title><style>body{margin:0;padding:32px 20px;background:#0d1117}main{max-width:960px;margin:auto;display:grid;gap:14px}img{display:block;width:100%;height:auto}nav{display:flex;gap:1.25%}nav a{width:32.5%}a{border-radius:20px}a:focus-visible{outline:3px solid #65d6c0;outline-offset:4px}@media(max-width:600px){body{padding:12px 8px}main{gap:8px}}</style><main>' + ''.join(items) + '</main></html>', encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--data-only", action="store_true")
    ap.add_argument("--import-calendar", type=Path)
    ap.add_argument("--as-of", type=date.fromisoformat)
    ap.add_argument("--static", action="store_true", default=os.environ.get("STATIC") == "1")
    args = ap.parse_args()
    profile = read_json(ROOT / "profile.json")
    if len(profile["links"]) != 3:
        raise ValueError("Exactly three linked tiles are required")
    for color in profile["brand"].values():
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Brand colors must be six-digit hex values")
    for repo in profile["featured"]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", repo["repo"]):
            raise ValueError("Invalid repository name")
    if args.refresh and args.import_calendar:
        ap.error("Choose --refresh or --import-calendar")
    end = args.as_of or datetime.now(timezone.utc).date()
    data_path = ROOT / "data" / "contributions.json"
    if args.refresh:
        atomic_json(data_path, refresh(profile["username"], end))
    elif args.import_calendar:
        atomic_json(data_path, import_calendar(args.import_calendar, profile["username"], end))
    if args.data_only:
        if not (args.refresh or args.import_calendar):
            ap.error("--data-only requires a refresh or import")
        print(f"Updated {data_path}")
        return
    data = validate_data(read_json(data_path), profile["username"])
    destination = ROOT / "preview" if args.static else ROOT
    renderer = Renderer(profile, data, destination / "cards", args.static)
    files = renderer.run()
    preview_html(profile, files, destination / "index.html" if args.static else ROOT / "preview.html", "cards")
    print(f"Rendered {len(files)} {'static' if args.static else 'animated'} cards to {renderer.out}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, HTTPError, URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
