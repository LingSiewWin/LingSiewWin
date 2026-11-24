"""Add effects to a Platane/snk snake SVG, timed to each tile the snake eats:
a glow behind the tile, a shockwave ring on it, and an equaliser bar under its column.
Also adds what the GitHub contribution graph shows: month and weekday labels and the
Less-More colour legend.

Usage: python3 neon_snake.py <snake.svg>   (rewrites the file in place)
Fails without writing if the SVG does not look like snk output."""
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GLOW = [(0, 0, .3), (120, .85, 1.15), (260, .75, .9), (400, .6, 1), (900, 0, 1)]   # ms, opacity, scale
RING = [(0, 1, .6), (250, .8, 3.3), (400, .5, 2.8), (650, 0, 3.1)]
BOUNCE = [(0, 0), (110, 1), (250, .4), (380, .62), (520, .3), (800, 0)]            # ms, bar height 0..1
SPREAD = {-1: .45, 0: 1, 1: .45}        # an eaten tile also nudges the neighbour columns
BASE = .12                              # resting bar height
BAR_Y, BAR_H = 116, 24                  # strip between the grid and the progress bar


TEXT = "#8b949e"                        # readable on GitHub's dark and light themes
PAD_LEFT, PAD_TOP, PAD_BOTTOM = 30, 8, 22


def labels(columns: int, colors: dict, today: date) -> str:
    """Month names on top, Mon/Wed/Fri on the left, Less-More legend bottom right.
    The last column is the week that holds `today`; weeks start on Sunday, as on GitHub."""
    # ponytail: uses the UTC date of the run, GitHub draws the graph in the profile's
    # timezone. Around a Sunday midnight the month labels can sit one column off until the next run.
    first = today - timedelta(days=(today.weekday() + 1) % 7) - timedelta(weeks=columns - 1)
    starts = [first + timedelta(weeks=c) for c in range(columns)]
    marks = [c for c in range(columns) if c == 0 or starts[c].month != starts[c - 1].month]
    marks = [c for i, c in enumerate(marks) if i + 1 == len(marks) or marks[i + 1] - c >= 2]   # no overlapping names
    out = [f'<text x="{c * 16 + 2}" y="-22">{starts[c]:%b}</text>' for c in marks]
    out += [f'<text x="-6" y="{row * 16 + 11.5}" text-anchor="end">{name}</text>'
            for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri"))]
    x0, y0 = columns * 16 - 2 - 30 - 5 * 16, 164
    out.append(f'<text x="{x0 - 6}" y="{y0 + 10}" text-anchor="end">Less</text>')
    out += [f'<rect x="{x0 + i * 16}" y="{y0}" width="12" height="12" rx="2" fill="{colors[f"c{i}"]}"/>' for i in range(5)]
    out.append(f'<text x="{x0 + 5 * 16 + 2}" y="{y0 + 10}">More</text>')
    return ('<g font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif" font-size="10" '
            f'fill="{TEXT}">' + "".join(out) + "</g>")


def grow(svg: str) -> str:
    """Widen the canvas for the labels and the legend."""
    m = re.search(r'<svg viewBox="(-?\d+) (-?\d+) (\d+) (\d+)" width="\d+" height="\d+"', svg)
    assert m, "unexpected <svg> header: snk output format changed"
    x, y, w, h = map(int, m.groups())
    w, h = w + PAD_LEFT, h + PAD_TOP + PAD_BOTTOM
    return svg.replace(m.group(0), f'<svg viewBox="{x - PAD_LEFT} {y - PAD_TOP} {w} {h}" width="{w}" height="{h}"', 1)


def bounce(dt: float) -> float:
    for (t0, h0), (t1, h1) in zip(BOUNCE, BOUNCE[1:]):
        if t0 <= dt <= t1:
            return h0 + (h1 - h0) * (dt - t0) / (t1 - t0)
    return 0


def shared_keyframes(name: str, stops, total: int) -> str:
    body = "".join(f"{ms / total * 100:.3f}%{{opacity:{o};transform:scale({s})}}" for ms, o, s in stops[:-1])
    ms, o, s = stops[-1]
    return f"@keyframes {name}{{{body}{ms / total * 100:.3f}%,100%{{opacity:{o};transform:scale({s})}}}}"


def bar_keyframes(col: int, events, total: int) -> str:
    """One keyframe list holding every bounce of this column's bar."""
    hits = [(t, SPREAD[c - col]) for t, _, _, c, _ in events if c - col in SPREAD]
    if not hits:
        return ""
    times = sorted({t + ms for t, _ in hits for ms, _ in BOUNCE if t + ms < total})
    stops = {}
    for t in times:
        h = min(1, sum(amp * bounce(t - t0) for t0, amp in hits))
        stops[f"{t / total * 100:.2f}"] = BASE + (1 - BASE) * h
    stops.pop("0.00", None), stops.pop("100.00", None)
    body = "".join(f"{p}%{{transform:scaleY({v:.2f})}}" for p, v in stops.items())
    return f"@keyframes b{col}{{0%,100%{{transform:scaleY({BASE})}}{body}}}.b.b{col}{{animation-name:b{col}}}"


def transform(svg: str, today: date) -> str:
    total = int(re.search(r"\.c\{[^}]*animation:none (\d+)ms", svg).group(1))
    colors = dict(re.findall(r"--(c\d):(#[0-9a-fA-F]{3,8})", svg))
    eaten = {n: (float(p), v) for n, p, v in re.findall(r"@keyframes (c\w+)\{([\d.]+)%\{fill:var\(--(c\d)\)\}", svg)}
    cells = re.findall(r'<rect class="c (c\w+)" x="(\d+)" y="(\d+)"', svg)
    assert cells and all(n in eaten for n, _, _ in cells), "no eaten tiles found: snk output format changed"
    columns = max(int(x) for x in re.findall(r'<rect class="c[^"]*" x="(\d+)"', svg)) // 16 + 1

    events = []                         # (eat time ms, tile centre x, y, column, colour var)
    for name, x, y in cells:
        pct, var = eaten[name]
        events.append((pct / 100 * total, int(x) + 6, int(y) + 6, int(x) // 16, var))

    css = (
        f".g,.r{{opacity:0;transform-box:fill-box;transform-origin:center;animation:g {total}ms linear infinite}}"
        f".r{{animation-name:r;fill:none;stroke-width:1.5px}}"
        f".b{{transform-box:fill-box;transform-origin:50% 100%;transform:scaleY({BASE});animation:none {total}ms linear infinite}}"
        + shared_keyframes("g", GLOW, total) + shared_keyframes("r", RING, total)
        + "".join(bar_keyframes(c, events, total) for c in range(columns))
    )
    defs = "<defs>" + "".join(
        f'<radialGradient id="g{v}"><stop offset="0" stop-color="{c}" stop-opacity=".9"/>'
        f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>'
        for v, c in colors.items() if v != "c0"
    ) + (
        f'<linearGradient id="eq" gradientUnits="userSpaceOnUse" x1="0" y1="{BAR_Y}" x2="0" y2="{BAR_Y + BAR_H}">'
        f'<stop offset="0" stop-color="{colors["c4"]}"/><stop offset="1" stop-color="{colors["c1"]}"/></linearGradient></defs>'
    )
    glows = "".join(f'<circle class="g" cx="{x}" cy="{y}" r="40" fill="url(#g{v})" style="animation-delay:{t:.0f}ms"/>'
                    for t, x, y, _, v in events)
    rings = "".join(f'<circle class="r" cx="{x}" cy="{y}" r="7" stroke="{colors[v]}" style="animation-delay:{t:.0f}ms"/>'
                    for t, x, y, _, v in events)
    bars = "".join(f'<rect class="b b{c}" x="{c * 16 + 2}" y="{BAR_Y}" width="12" height="{BAR_H}" rx="2" fill="url(#eq)"/>'
                   for c in range(columns))

    assert svg.count("</style>") == 1
    svg = svg.replace("</style>", css + "</style>" + defs + glows)      # glows sit behind the tiles
    front = re.search(r'<rect class="[us] ', svg)                       # progress bar, else the snake
    assert front, "no progress bar or snake found: snk output format changed"
    svg = svg[:front.start()] + bars + rings + svg[front.start():]
    return grow(svg).replace("</svg>", labels(columns, colors, today) + "</svg>")


if __name__ == "__main__":
    path = Path(sys.argv[1])
    out = transform(path.read_text(), datetime.now(timezone.utc).date())
    path.write_text(out)
    print(f"{path}: {out.count('class=\"g\"')} eaten tiles wired, {len(out)} bytes")
