# Aqeel Ali GitHub profile

Copy the contents of this folder, including `.github/`, into `Aqeel-ali/aqeel-ali`.
Keep the generated `README.md` at the repository root. Commit and push these
files, then open **Actions → Refresh profile cards → Run workflow** once.
The daily schedule runs on the default branch at 03:17 UTC, approximately
06:17 in Baghdad. GitHub can delay scheduled runs.

## Render locally

Requires Python 3.11 or newer. No network is needed to render the included data.

```sh
python -m pip install -r requirements.txt
python scripts/render_cards.py
```

The single Python script writes all nine SVG cards into `cards/`, generates
`README.md`, and writes `preview.html`. Open the preview in a browser; it uses
real `<img>` elements, the same embedding context used by the README.

For a static final-frame preview, use either of these commands:

```sh
# macOS / Linux
STATIC=1 python scripts/render_cards.py
```

```powershell
# PowerShell
$env:STATIC = '1'
python scripts/render_cards.py
Remove-Item Env:STATIC
```

Or run `python scripts/render_cards.py --static` on any platform. Open
`preview/index.html`. Static mode writes a separate `preview/` directory and
preserves the animated cards used by the main README. Static SVGs contain no
animation nodes or keyframes. Both animated and static output are included in
this delivery; `preview/` is ignored by Git by default.

## Edit content and appearance

Edit `profile.json`, then rerun the renderer. It contains the colours, three
external links, and curated public repositories. The original profile's blue
banner and dark navy artwork supplied the visual direction. There was no
personal website to match. Space Grotesk and JetBrains Mono are new font
choices, not fonts claimed to come from a website.

The introduction uses the user's latest description: Flutter developer and
UI/UX designer with **3 years of experience**. The résumé was used as reference
material, and the old student description has been removed. Featured cards
link to verified public repositories; they do not imply that private client
applications have public source code. Add more featured entries to generate
more cards automatically.

Optional portrait: put a PNG or JPEG in `assets/`, and set `portrait` to its
repository-relative path in `profile.json`. It replaces the phone illustration
and is embedded as a data URI, so the SVG has no external asset requests.

Original font files and their SIL Open Font Licenses are in `assets/fonts/`.
The renderer calls `python -m fontTools.subset`, the implementation of
`pyftsubset`, to produce WOFF subsets. Each SVG includes its fonts in an inline
`<style>` block as base64 WOFF data URIs. Font subset results are cached locally
in `.font-cache/`, which is ignored by Git.

## Data and daily refresh

`data/contributions.json` is a real snapshot imported from the public GitHub
contribution calendar, with an explicit source and UTC date. The renderer
never invents activity and never fetches data during a normal local render.

The scheduled Action first fetches the calendar through GitHub's GraphQL API,
validates a complete sequence of dates and nonnegative counts, then saves
the JSON atomically. A second step renders the cards; the last step commits
the JSON, cards, and generated README. API errors fail the run and preserve
the previous valid JSON; missing days are never silently filled with zero.
No secrets are saved to the JSON or images.

The built-in `github.token` is used by default. If the account or organization
requires another credential for calendar visibility, create an Actions secret
named `PROFILE_TOKEN` with permission to read the desired contribution data.
Do not paste tokens into the code or JSON. The workflow needs `contents: write`
for committing; repository rules that forbid bot pushes must permit this
workflow or use your normal review process. The scheduled workflow begins
running after these files are pushed to GitHub; this local delivery does not
install or activate it on your account.

To refresh locally, set `GH_TOKEN` in your environment, then run:

```sh
python scripts/render_cards.py --refresh --data-only
python scripts/render_cards.py
```

## What the numbers mean

- Window: twelve calendar months, including the current partial month, ending
  on the snapshot's UTC date. Monthly bars and the daily grid share this window.
- Contributions: GitHub calendar counts, which include more than commits.
  Visibility depends on the authenticated token and GitHub profile settings.
- Active days: dates with one or more contributions in the window.
- Current streak: consecutive active dates ending today, or yesterday if today
  has no contributions yet. It is measured within the saved window.
- Longest streak: longest consecutive run of active dates in the saved window.
- Busiest day: highest count; the most recent date wins a tie. An empty calendar
  shows `None` instead of claiming a busiest day.
- Graph: Sunday-first grid. Days outside the saved window are blank. Positive
  counts use a blue intensity scale; the highest intensity is the brand colour.

## Motion and accessibility

All graphics are native SVG with inline CSS. There is no JavaScript,
`foreignObject`, external stylesheet, external font, or external image.
CSS keyframes stagger the cards from top to bottom. A finite SMIL animation
draws the decorative halo. With `prefers-reduced-motion: reduce`, CSS animations
and transitions are disabled, the SMIL layer is hidden, and an identical static
layer is shown. The hidden SMIL timeline cannot be paused through CSS alone;
it has no visible output in reduced-motion mode. Static mode omits it entirely.

Each SVG has a title and description. README images have alternative text, and
the three link tiles each use an outer HTML `<a>` around an `<img width="32.5%">`.
Links inside an SVG image would not be interactive. Animation starts when each
image loads; independent SVG images cannot share a synchronized clock, and
GitHub image caching or lazy loading can affect the apparent stagger.

## Validation performed

All nine cards were checked in Chromium through actual `<img>` elements at
desktop and 390-pixel viewport widths. Embedded WOFF fonts loaded, SVG text
stayed inside each viewport, and the completed animated frames matched the
static screenshot pixel for pixel. The browser's native reduced-motion
preference produced the same static frame and no visible changes over time.
Contribution calculations were checked for empty activity, gaps, ties, leap
years, and current streaks ending today or yesterday. The GraphQL response and
error paths were tested with local mock responses. The authenticated daily
refresh still needs its first run in your GitHub repository.

## Reference sources

- [Original profile](https://github.com/Aqeel-ali/aqeel-ali)
- [Public contribution calendar](https://github.com/users/Aqeel-ali/contributions)
- [EduLab](https://github.com/Aqeel-ali/edulab)
- [Simple Morty](https://github.com/Aqeel-ali/Simple_Morty)
- [Senya](https://github.com/Aqeel-ali/Senya_learning)
- [SVG image restrictions](https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/SVG_as_an_image)
- [FontTools subset command](https://fonttools.readthedocs.io/en/latest/subset/index.html)
- [GitHub workflow scheduling](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
