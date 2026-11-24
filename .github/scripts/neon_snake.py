"""Night drive: turns a Platane/snk contribution snake into a car that remembers what it ate.

Three linked ideas, all driven by the real route and the real daily contribution counts:
  battery  the car charges with every day it eats: its body heats up (cool, amber, yellow,
           pink-white), its headlights and glow grow, and its light trail gets longer
  route    the car draws its drive as one neon line; each eaten day leaves a node sized by
           that day's count; after the last day the whole route lights up once
  skyline  each week owns a building under the grid; eating a day raises it and it stays up

On the drive home the car gives it all back: as it passes a column, that week's building
sinks and its tiles light again, so the loop point has no jump.

Also draws what GitHub's own graph shows: month and weekday labels and the Less-More legend.
Under prefers-reduced-motion nothing moves: full grid, finished skyline, parked car.

Usage: python3 neon_snake.py <snk-raw.svg> <route.json> <out.svg>
Both inputs come from route.ts. Fails without writing if the SVG does not look like snk output."""
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OUT = "cubic-bezier(.16,1,.3,1)"        # fast start, long settle: no overshoot
INOUT = "cubic-bezier(.65,0,.35,1)"
TEXT = "#8b949e"                        # readable on GitHub's dark and light themes
NAVY = (0x1a, 0x1b, 0x3a)
PAD_LEFT, PAD_TOP = 30, 8               # room for the weekday and month labels

# battery
CHARGE_P = .75                          # charge per eaten day = count ** P, so small days still register
TRAIL_BASE, TRAIL_EXTRA = 3, 10         # trail dots: always there, and added at full charge
COOL, AMBER, SUN, CORE, CORE_RIM = "#5f86a6", "#ff7a1a", "#ffd23f", "#ffe6f5", "#ff5fd2"
GLASS, HEADLIGHT, TAILLIGHT = "#10122b", "#fff3b0", "#ff2e63"
HALO_R, BEAM_LEN = 34, 30

# route
LINE_W, LINE_OPACITY, NODE_IN = 1.4, .5, 400

# skyline
SKY_TOP, HMAX, HMIN = 124, 80, 3        # top of the tallest building, tallest and lowest height
GROUND = SKY_TOP + HMAX
WEEK_P = 2                              # week size = (sum of day_count ** P) ** (1 / P): one giant day outweighs many small ones
RISE_MS, RISE_PER_UNIT = 300, 12
WINDOW = "#ffd23f"


def clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def heat_amber(q): return clamp(q / .15)
def heat_sun(q): return clamp((q - .15) / .35)
def heat_core(q): return clamp((q - .7) / .3)


def wall(color: str) -> str:
    """Building wall: the level colour sunk into the tile navy, so it shows on dark and white pages."""
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(.42 * c + .58 * n):02x}" for c, n in zip(rgb, NAVY))


def tower(size: float) -> float:
    """Building height for a week size in 0..1. The low term keeps small weeks visible,
    the squared term makes the biggest weeks stand clear of the rest."""
    return HMIN + (HMAX - HMIN) * (.55 * size ** .4 + .45 * size ** 2)


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
    x0, y0 = columns * 16 - 2 - 30 - 5 * 16, GROUND + 10
    out.append(f'<text x="{x0 - 6}" y="{y0 + 10}" text-anchor="end">Less</text>')
    out += [f'<rect x="{x0 + i * 16}" y="{y0}" width="12" height="12" rx="2" fill="{colors[f"c{i}"]}"/>' for i in range(5)]
    out.append(f'<text x="{x0 + 5 * 16 + 2}" y="{y0 + 10}">More</text>')
    return ('<g font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif" font-size="10" '
            f'fill="{TEXT}">' + "".join(out) + "</g>")


def build(svg: str, route: dict, today: date) -> str:
    loop, step_ms, columns = route["loopMs"], route["stepMs"], route["columns"]
    eats, heads = route["eats"], [s[0] for s in route["snake"]]
    assert f"linear {loop}ms infinite" in svg, "loop length differs between the svg and route.json"
    assert svg.count("</style>") == 1 and "@keyframes s0{" in svg, "snake keyframes not found: snk output format changed"
    colors = dict(re.findall(r"--(c[0-4]):(#[0-9a-fA-F]{6})", svg))
    assert len(colors) == 5, "tile colours not found: snk output format changed"
    assert len(heads) == route["steps"] and heads[0] == heads[-1], "route is not a closed loop"
    assert all(abs(ax - bx) + abs(ay - by) == 1 for (ax, ay), (bx, by) in zip(heads, heads[1:-1])), "the head jumps"
    assert all(heads[e["step"]] == [e["col"], e["row"]] for e in eats), "eats are not on the head route"
    assert eats == sorted(eats, key=lambda e: e["ms"]), "eats are not in time order"

    def pct(ms: float) -> str:
        return f"{clamp(ms / loop) * 100:.3f}".rstrip("0").rstrip(".") + "%"

    # ---- canvas: room for labels, skyline and legend; snk's own snake and progress bar go ----
    m = re.search(r'<svg viewBox="(-?\d+) (-?\d+) (\d+) (\d+)" width="\d+" height="\d+"', svg)
    assert m, "unexpected <svg> header: snk output format changed"
    x, y, w, _ = map(int, m.groups())
    w, h = w + PAD_LEFT, GROUND + 28 - (y - PAD_TOP)
    svg = svg.replace(m.group(0), f'<svg viewBox="{x - PAD_LEFT} {y - PAD_TOP} {w} {h}" width="{w}" height="{h}"', 1)
    svg, n = re.subn(r'<rect class="s s\d"[^>]*/>', "", svg)
    assert n == 4, "expected a 4-segment snake: snk output format changed"
    svg = re.sub(r'<rect class="u u\d+"[^>]*/>', "", svg)
    svg = re.sub(r"@keyframes (?:s[1-9]|u\d+)\{(?:[^{}]*\{[^{}]*\})*\}", "", svg)
    svg = re.sub(r"\.(?:s\.s\d|u\.u\d+|u)\{[^}]*\}", "", svg)
    assert "@keyframes s0{" in svg

    if not eats:                         # an empty year: nothing to remember, just the labelled grid
        return svg.replace("</svg>", labels(columns, colors, today) + "</svg>")

    # ---- time anchors: everything after the last eat happens on the drive home -----------------
    last = eats[-1]["ms"]
    home = loop - last                   # length of the drive home
    assert home > 0
    full_until = last + .10 * home       # charge is held, then given back
    empty_at = loop - .04 * home
    sink_ms = min(400, .08 * home)
    line_hold, line_off = last + .53 * home, last + .80 * home
    pulse = (last + .02 * home, last + .07 * home, last + .39 * home)

    # ---- battery: the charge curve ----------------------------------------------------------
    weights = [e["count"] ** CHARGE_P for e in eats]
    total = sum(weights)
    q, curve, q_after = 0.0, [(0, 0.0, False)], []          # (ms, charge 0..1, ease out to the next stop)
    for i, (e, wgt) in enumerate(zip(eats, weights)):
        gap = (eats[i + 1]["ms"] if i + 1 < len(eats) else full_until) - e["ms"]
        curve.append((e["ms"], q, gap > step_ms))
        q += wgt / total
        q_after.append(q)
        curve.append((e["ms"] + min(gap, 300), q, False))
    curve += [(full_until + (empty_at - full_until) * i / 20, 1 - i / 20, False) for i in range(21)]
    curve.append((loop, 0.0, False))

    def charge_keyframes(name: str, fmt) -> str:
        """One @keyframes that follows the charge curve; stops that change nothing are dropped."""
        pts = [(ms, fmt(c), ease) for ms, c, ease in curve]
        keep = [p for i, p in enumerate(pts)
                if i in (0, len(pts) - 1) or not (pts[i - 1][1] == p[1] == pts[i + 1][1])]
        merged = {}
        for ms, css, ease in keep:       # a later stop at the same time wins
            merged[pct(ms)] = css + (f";animation-timing-function:{OUT}" if ease else "")
        return f"@keyframes {name}{{" + "".join(f"{k}{{{v}}}" for k, v in merged.items()) + "}"

    css = [
        f".x-m{{animation:s0 {loop}ms linear infinite}}",
        f".x-r{{transform-origin:8px 8px;animation:x-r {loop}ms linear infinite}}",
        f".x-a,.x-y,.x-c{{opacity:0;animation:x-a {loop}ms linear infinite}}",
        f".x-a{{fill:{AMBER}}}.x-y{{fill:{SUN};animation-name:x-y}}",
        f".x-c{{fill:{CORE};stroke:{CORE_RIM};stroke-width:.8px;animation-name:x-c}}",
        f".x-h{{transform-origin:8px 8px;opacity:0;animation:x-h {loop}ms linear infinite}}",
        f".x-w{{transform-origin:18px 8px;opacity:0;animation:x-w {loop}ms linear infinite}}",
        f".x-t{{fill:{TAILLIGHT}}}",
        f".x-e{{transform-box:fill-box;transform-origin:center;transform:scale(0);animation:none {loop}ms linear infinite}}",
        charge_keyframes("x-a", lambda c: f"opacity:{heat_amber(c):.2f}"),
        charge_keyframes("x-y", lambda c: f"opacity:{heat_sun(c):.2f}"),
        charge_keyframes("x-c", lambda c: f"opacity:{heat_core(c):.2f}"),
        charge_keyframes("x-h", lambda c: f"opacity:{clamp(c * 4):.2f};transform:scale({.3 + .7 * c ** 1.5:.3f})"),
        charge_keyframes("x-w", lambda c: f"opacity:{.35 + .5 * c:.2f};transform:scale({.45 + .55 * c:.3f},1)"),
    ]

    # ---- the car: follows snk's head keyframes (s0) and turns to face the way it drives ---------
    angle_of = {(1, 0): 0, (0, 1): 90, (-1, 0): 180, (0, -1): 270}
    moves = [(bx - ax, by - ay) for (ax, ay), (bx, by) in zip(heads, heads[1:-1])]
    moves.append(moves[0])               # the last step stands still: use it to turn towards the first move
    angles, cur = [], angle_of[moves[0]]             # so the loop starts and ends facing the first move
    start = cur
    for mv in moves:
        cur += (angle_of[mv] - cur + 180) % 360 - 180            # shortest turn
        angles.append(cur)
    turn = min(40, step_ms * .4)
    stops, prev = [f"0%{{transform:rotate({start}deg)}}"], start
    for i, a in enumerate(angles):
        if a != prev:
            t = i * step_ms
            stops.append(f"{pct(t)}{{transform:rotate({prev}deg);animation-timing-function:{INOUT}}}")
            stops.append(f"{pct(t + 2 * turn)}{{transform:rotate({a}deg)}}")
            prev = a
    assert (prev - start) % 360 == 0, "the car does not end facing the way it started"
    stops.append(f"100%{{transform:rotate({prev}deg)}}")
    css.append("@keyframes x-r{" + "".join(stops) + "}")

    body = 'x="-2" y="3" width="20" height="10" rx="3.6"'
    car = (
        f'<g class="x-m" style="transform:translate({heads[0][0] * 16}px,{heads[0][1] * 16}px)">'
        f'<circle class="x-h" cx="8" cy="8" r="{HALO_R}" fill="url(#x-hg)"/>'
        f'<g class="x-r" style="transform:rotate({start}deg)">'
        f'<path class="x-w" d="M18,4.6L{18 + BEAM_LEN},-3V19L18,11.4Z" fill="url(#x-wg)"/>'
        f'<rect {body} fill="{COOL}"/><rect class="x-a" {body}/><rect class="x-y" {body}/>'
        f'<rect class="x-c" x="12.6" y="5.2" width="3.4" height="5.6" rx="1.4"/>'
        f'<rect x="3.2" y="4.5" width="8.6" height="7" rx="2.2" fill="{GLASS}" opacity=".88"/>'
        f'<rect x="5.6" y="5.6" width="4.2" height="4.8" rx="1.2" fill="{COOL}" opacity=".55"/>'
        f'<rect x="16.5" y="3.9" width="1.5" height="2.3" rx=".6" fill="{HEADLIGHT}"/>'
        f'<rect x="16.5" y="9.8" width="1.5" height="2.3" rx=".6" fill="{HEADLIGHT}"/>'
        f'<rect class="x-t" x="-2" y="3.9" width="1.3" height="2.3" rx=".5"/>'
        f'<rect class="x-t" x="-2" y="9.8" width="1.3" height="2.3" rx=".5"/></g></g>'
    )

    # ---- light trail: dot k sits where the car was k steps ago; charge adds dots -----------------
    trail = []
    for k in range(1, TRAIL_BASE + TRAIL_EXTRA + 1):
        r = max(1.4, 3.2 - .14 * k)
        px, py = heads[-1 - k] if k < len(heads) else heads[0]
        dot = f'<circle class="x-t" cx="8" cy="8" r="{r:.1f}" opacity="{max(.35, .95 - .045 * k):.2f}"/>'
        if k > TRAIL_BASE:
            j = k - TRAIL_BASE
            on = next(e["ms"] for e, qa in zip(eats, q_after) if qa >= j / TRAIL_EXTRA - 1e-9)
            on = max(on, (k + 1) * step_ms)                      # never before the dot has a past to sit on
            off = full_until + (1 - j / TRAIL_EXTRA) * (empty_at - full_until)
            fade = min(300, (loop - off) * .9)
            if on + 300 >= off:
                continue                                         # no room in this loop: the dot never grows
            css.append(f"@keyframes x-e{k}{{0%,{pct(on)}{{transform:scale(0);animation-timing-function:{OUT}}}"
                       f"{pct(on + 300)},{pct(off)}{{transform:scale(1)}}{pct(off + fade)},100%{{transform:scale(0)}}}}")
            dot = f'<g class="x-e" style="animation-name:x-e{k}">{dot}</g>'
        trail.append(f'<g class="x-m" style="transform:translate({px * 16}px,{py * 16}px);'
                     f'animation-delay:{k * step_ms - loop}ms">{dot}</g>')
    trail.reverse()                      # far dots first, so nearer ones sit on top

    # ---- route: a line that grows under the car, one node per eaten day -------------------------
    # Drawn as one bar per straight run, grown by transform. A single dashed path would be one
    # element, but WebKit renders a long dashed path with stray pieces, so no dashes here.
    last_step = eats[-1]["step"]
    pts = heads[:last_step + 1]
    d = "M" + "L".join(f"{cx * 16 + 8},{cy * 16 + 8}" for cx, cy in pts)
    css += [
        f".x-g{{animation:x-g {loop}ms linear infinite}}",
        f"@keyframes x-g{{0%,{pct(line_hold)}{{opacity:1}}{pct(line_off)},100%{{opacity:0}}}}",
        f".x-l{{fill:{colors['c2']};opacity:{LINE_OPACITY};transform-box:fill-box;animation:none {loop}ms linear infinite}}",
        ".x-l0{transform-origin:0 50%;transform:scale(0,1)}.x-l1{transform-origin:100% 50%;transform:scale(0,1)}",
        ".x-l2{transform-origin:50% 0;transform:scale(1,0)}.x-l3{transform-origin:50% 100%;transform:scale(1,0)}",
        f".x-p{{fill:none;stroke:{colors['c3']};stroke-width:2.6px;stroke-linejoin:round;opacity:0;animation:x-p {loop}ms linear infinite}}",
        f"@keyframes x-p{{0%,{pct(pulse[0])}{{opacity:0;animation-timing-function:{OUT}}}"
        f"{pct(pulse[1])}{{opacity:.75;animation-timing-function:ease-out}}{pct(pulse[2])},100%{{opacity:0}}}}",
        f".x-n{{transform:scale(0);transform-box:fill-box;transform-origin:center;stroke-opacity:.3;animation:none {loop}ms linear infinite}}",
    ]
    runs, i0, half = [], 0, LINE_W / 2
    for i in range(1, len(pts)):
        if i == len(pts) - 1 or (pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) != (pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]):
            (ax, ay), (bx, by) = pts[i0], pts[i]
            kind = 0 if bx > ax else 1 if bx < ax else 2 if by > ay else 3      # grows right, left, down, up
            hidden = "scale(0,1)" if kind < 2 else "scale(1,0)"
            css.append(f"@keyframes x-u{len(runs)}{{0%,{pct(i0 * step_ms)}{{transform:{hidden}}}{pct(i * step_ms)},100%{{transform:scale(1)}}}}")
            runs.append(f'<rect class="x-l x-l{kind}" x="{min(ax, bx) * 16 + 8 - half:.1f}" y="{min(ay, by) * 16 + 8 - half:.1f}" '
                        f'width="{abs(bx - ax) * 16 + LINE_W:.1f}" height="{abs(by - ay) * 16 + LINE_W:.1f}" style="animation-name:x-u{len(runs)}"/>')
            i0 = i
    nodes = []
    for i, e in enumerate(eats):
        r, c = .9 + .44 * math.sqrt(e["count"]), colors[f"c{e['level']}"]
        css.append(f"@keyframes x-n{i}{{0%,{pct(e['ms'])}{{transform:scale(0);animation-timing-function:{OUT}}}"
                   f"{pct(e['ms'] + NODE_IN)},100%{{transform:scale(1)}}}}")
        nodes.append(f'<circle class="x-n" cx="{e["col"] * 16 + 8}" cy="{e["row"] * 16 + 8}" r="{r:.1f}" fill="{c}" '
                     f'stroke="{c}" stroke-width="{r * .7:.1f}" style="animation-name:x-n{i}"/>')
    route_layer = f'<g class="x-g"><path class="x-p" d="{d}"/>{"".join(runs)}{"".join(nodes)}</g>'

    # ---- the drive home: when the car leaves a column, that column is given back ----------------
    given_back = {}                      # column -> ms
    for step in range(last_step, len(heads)):
        given_back[heads[step][0]] = step * step_ms
    sweep_from = heads[min(len(heads) - 1, math.ceil(full_until / step_ms))][0]   # where the car is when it starts giving back
    back_end = loop - sink_ms - 50
    held = .25 * home                    # the finished city and route are held this long first

    def back_time(col: int) -> float:
        t = given_back.get(col, 0)
        if t < full_until:               # columns the car does not pass again: a quick sweep outwards
            t = full_until + abs(col - sweep_from) * step_ms / 2
        t = min(max(t, full_until), back_end)
        # the wake starts `held` behind the car and catches up with it by the end of the loop
        return full_until + held + (t - full_until) * (back_end - full_until - held) / (back_end - full_until)

    tile_col = {name: int(tx) // 16 for name, tx in re.findall(r'<rect class="c (c\w+)" x="(\d+)"', svg)}

    def relight(mo):
        name, lit, level, eaten = mo.groups()
        t = back_time(tile_col[name]) + sink_ms / 2
        return (f"@keyframes {name}{{{lit}%{{fill:var(--{level})}}{eaten}%,{pct(t)}{{fill:var(--ce)}}"
                f"{pct(t + 100)},100%{{fill:var(--{level})}}}}")

    svg, relit = re.subn(r"@keyframes (c\w+)\{([\d.]+)%\{fill:var\(--(c\d)\)\}([\d.]+)%,100%\{fill:var\(--ce\)\}\}", relight, svg)
    assert relit == len(eats), f"expected {len(eats)} eaten tiles in the svg, found {relit}"

    # ---- skyline: one building per week, latched --------------------------------------------------
    by_col = defaultdict(list)
    for e in eats:
        by_col[e["col"]].append(e)
    size = lambda es: sum(e["count"] ** WEEK_P for e in es) ** (1 / WEEK_P)
    top = max(size(es) for es in by_col.values())
    css += [f".x-b{{transform:translateY({HMAX}px);animation:none linear {loop}ms infinite}}",
            ".x-o{opacity:0}",
            f".x-k{{opacity:0;transform-box:fill-box;transform-origin:center;animation:x-k linear {loop}ms infinite}}"]
    buildings, beacon_at = [], None
    windows = [                          # two window layouts, drawn once and reused by every building
        f'<path id="x-w{v}" fill="{WINDOW}" d="' + "".join(
            f"M{4 + 5 * side},{5 + 5 * row}h3v2.5h-3z" for row in range((HMAX - 8) // 5) for side in range(2)
            if (row * 7 + side * 3 + v * 5) % 4) + '"/>'
        for v in range(2)]

    def building(col: int, level: int, extra: str, style: str) -> str:
        c, bx = colors[f"c{level}"], col * 16 + 2
        return (f'<g class="x-b{extra}" style="{style}"><rect x="{bx}" y="{SKY_TOP}" width="12" height="{HMAX}" fill="{wall(c)}"/>'
                f'<rect x="{bx}" y="{SKY_TOP}" width="12" height="2" fill="{c}"/>'
                f'<use href="#x-w{col % 2}" x="{col * 16}" y="{SKY_TOP}"/></g>')

    for col in sorted(by_col):
        es, t_off = by_col[col], back_time(col)
        stops, cur, final = {0: (0, None)}, 0.0, 0.0
        for i, e in enumerate(es):
            hgt = tower(size(es[:i + 1]) / top)
            nxt = es[i + 1]["ms"] if i + 1 < len(es) else t_off
            stops[e["ms"]] = (cur, OUT)
            stops[min(e["ms"] + RISE_MS + RISE_PER_UNIT * (hgt - cur), nxt)] = (hgt, None)
            cur = final = hgt
        stops[t_off] = (cur, INOUT)
        stops[t_off + sink_ms] = (0, None)
        stops[loop] = (0, None)
        assert list(stops) == sorted(stops), f"building {col}: keyframes out of order"
        css.append(f"@keyframes x-b{col}{{" + "".join(
            f"{pct(t)}{{transform:translateY({HMAX - v:.1f}px)" + (f";animation-timing-function:{ease}" if ease else "") + "}"
            for t, (v, ease) in stops.items()) + "}")
        rest = f"--f:translateY({HMAX - final:.1f}px)"           # finished height, for reduced motion
        buildings.append(building(col, es[0]["level"], "", f"{rest};animation-name:x-b{col}"))
        seen = es[0]["level"]
        for e in es:                     # a higher colour level eaten later repaints the building
            if e["level"] > seen:
                seen = e["level"]
                css.append(f"@keyframes x-o{col}-{seen}{{0%,{pct(e['ms'])}{{opacity:0}}{pct(e['ms'] + 200)},{pct(t_off + sink_ms)}{{opacity:1}}"
                           f"{pct(t_off + sink_ms + 1)},100%{{opacity:0}}}}")
                buildings.append(building(col, seen, " x-o", f"{rest};animation-name:x-b{col},x-o{col}-{seen}"))
        if size(es) == top:
            beacon_at = (col, es[-1]["ms"] + RISE_MS, t_off, final)

    col, t_on, t_off, final = beacon_at  # the single accent: a beacon on the tallest roof
    css.append(f"@keyframes x-k{{0%,{pct(t_on)}{{opacity:0;transform:scale(.3);animation-timing-function:{OUT}}}"
               f"{pct(t_on + 400)},{pct(t_off)}{{opacity:1;transform:scale(1)}}{pct(t_off + 200)},100%{{opacity:0;transform:scale(1)}}}}")
    city = (f'<g clip-path="url(#x-clip)">{"".join(buildings)}</g>'
            f'<rect x="0" y="{GROUND}" width="{columns * 16}" height="1.5" rx=".75" fill="{colors["c2"]}" opacity=".75"/>'
            f'<circle class="x-k" cx="{col * 16 + 8}" cy="{GROUND - final - 6:.1f}" r="8" fill="url(#x-kg)"/>')

    defs = (
        "<defs>" + "".join(windows)
        + f'<clipPath id="x-clip"><rect x="-16" y="{SKY_TOP - 8}" width="{columns * 16 + 32}" height="{HMAX + 8}"/></clipPath>'
        f'<radialGradient id="x-kg"><stop offset="0" stop-color="{SUN}"/><stop offset=".3" stop-color="{SUN}"/>'
        f'<stop offset=".34" stop-color="{SUN}" stop-opacity=".45"/><stop offset="1" stop-color="{SUN}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="x-hg"><stop offset="0" stop-color="{SUN}" stop-opacity=".55"/>'
        f'<stop offset=".5" stop-color="{CORE_RIM}" stop-opacity=".25"/><stop offset="1" stop-color="{CORE_RIM}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="x-wg" gradientUnits="userSpaceOnUse" x1="18" x2="{18 + BEAM_LEN}">'
        f'<stop offset="0" stop-color="{HEADLIGHT}" stop-opacity=".8"/><stop offset="1" stop-color="{HEADLIGHT}" stop-opacity="0"/></linearGradient>'
        "</defs>"
    )
    calm = "@media (prefers-reduced-motion:reduce){*{animation:none!important}.x-b{transform:var(--f)}.x-o{opacity:1}}"
    svg = svg.replace("</style>", "".join(css) + calm + "</style>" + defs)
    svg = svg.replace("</svg>", city + route_layer + "".join(trail) + car + labels(columns, colors, today) + "</svg>")
    assert "<script" not in svg and "<animate" not in svg and not re.search(r'href="(?!#)', svg), "nothing may load from outside the file"
    return svg


if __name__ == "__main__":
    raw_path, route_path, out_path = map(Path, sys.argv[1:4])
    raw = raw_path.read_text()
    route = json.loads(route_path.read_text())
    out = build(raw, route, datetime.now(timezone.utc).date())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out)
    count = lambda s: len(re.findall(r"<(?:rect|circle|path|g|text|pattern|stop)\b", s))
    print(f"{out_path}: {len(route['eats'])} eaten days, {out.count('class=\"x-n\"')} route nodes, "
          f"{count(raw)} -> {count(out)} elements, {len(raw.encode())} -> {len(out.encode())} bytes")
