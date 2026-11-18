#!/usr/bin/env python3
"""THE DAY IN WORLD NEWS — Wednesday 18 November 2026.

Draws a one-page newspaper front page summing up the world's news of
Wednesday 18 November 2026 and writes it to /output/entry.png (or to
$MAKEFUN_OUTPUT_DIR/entry.png when that variable is set).

The grading sandbox is a stock python:3.13-slim image — standard library
only — so this program renders everything itself: a software rasteriser
over a bytearray framebuffer, glyph coverage baked at build time into
fonts.bin by gen_fonts.py (Liberation Sans), and a PNG encoder built on
zlib. No network, no randomness, no clock: two runs write identical bytes.

Layout: a dense broadsheet — masthead strip, a large date headline, three
lead panels with drawn art, a numbered grid of the day's main stories, a
dotted world map with numbered pins, and a numbered briefs list.
Story selection and sourcing: see SOURCES.md.
"""

import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

PAGE_W = 1024
PAGE_H = 1024

PAPER = (247, 243, 234)
PANEL = (253, 251, 246)
INK = (22, 24, 29)
DECK = (48, 50, 56)
FAINT = (110, 105, 94)
BORDER = (203, 195, 175)
RED = (163, 38, 32)
BLUE = (30, 74, 140)
GREEN = (26, 102, 70)
TEAL = (13, 106, 122)
BROWN = (146, 96, 20)
PLUM = (138, 42, 108)
SLATE = (84, 102, 118)
SAND = (233, 226, 208)
LAND = (219, 203, 164)
SEA = (198, 213, 219)
DOTO = (168, 156, 128)


# ---------------------------------------------------------------- fonts

class Glyph:
    __slots__ = ("advance", "left", "top", "w", "h", "data")

    def __init__(self, advance, left, top, w, h, data):
        self.advance = advance
        self.left = left
        self.top = top
        self.w = w
        self.h = h
        self.data = data


class Font:
    __slots__ = ("ascent", "descent", "glyphs")

    def __init__(self, ascent, descent, glyphs):
        self.ascent = ascent
        self.descent = descent
        self.glyphs = glyphs

    def char_width(self, ch):
        glyph = self.glyphs.get(ord(ch))
        return glyph.advance if glyph else 0.0

    def text_width(self, text, tracking=0.0):
        width = sum(self.char_width(ch) for ch in text)
        if tracking and len(text) > 1:
            width += tracking * (len(text) - 1)
        return width

    def wrap(self, text, max_width, tracking=0.0):
        """Greedy word wrap; returns a list of lines that fit max_width."""
        lines = []
        current = ""
        for word in text.split(" "):
            trial = word if not current else current + " " + word
            if self.text_width(trial, tracking) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines


def load_fonts():
    raw = zlib.decompress(open(os.path.join(HERE, "fonts.bin"), "rb").read())
    assert raw[:5] == b"MFNT1", "bad fonts.bin"
    pos = 5
    (count,) = struct.unpack_from("<H", raw, pos)
    pos += 2
    fonts = {}
    for _ in range(count):
        (name_len,) = struct.unpack_from("<B", raw, pos)
        pos += 1
        name = raw[pos:pos + name_len].decode("ascii")
        pos += name_len
        ascent, descent, glyph_count = struct.unpack_from("<h h H", raw, pos)
        pos += 6
        glyphs = {}
        for _ in range(glyph_count):
            cp, adv_q, left, top, w, h, dlen = struct.unpack_from(
                "<I H h h H H I", raw, pos)
            pos += 18
            data = raw[pos:pos + dlen]
            pos += dlen
            glyphs[cp] = Glyph(adv_q / 64.0, left, top, w, h, data)
        fonts[name] = Font(ascent, descent, glyphs)
    return fonts


# ---------------------------------------------------------------- canvas

class Canvas:
    """A minimal RGB rasteriser: flat shapes and coverage-blended text."""

    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(bytes(bg) * (w * h))

    def _offset(self, x, y):
        return (y * self.w + x) * 3

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = self._offset(x, y)
            self.px[i:i + 3] = bytes(color)

    def blend(self, x, y, color, cov):
        """Blend color over the current pixel; cov is coverage 0..15."""
        if cov <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = self._offset(x, y)
        if cov >= 15:
            self.px[i:i + 3] = bytes(color)
            return
        inv = 15 - cov
        self.px[i] = (color[0] * cov + self.px[i] * inv + 7) // 15
        self.px[i + 1] = (color[1] * cov + self.px[i + 1] * inv + 7) // 15
        self.px[i + 2] = (color[2] * cov + self.px[i + 2] * inv + 7) // 15

    def rect(self, x0, y0, x1, y1, color):
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.w, x1)
        y1 = min(self.h, y1)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for y in range(y0, y1):
            i = self._offset(x0, y)
            self.px[i:i + len(row)] = row

    def frame(self, x0, y0, x1, y1, color, t=1):
        self.rect(x0, y0, x1, y0 + t, color)
        self.rect(x0, y1 - t, x1, y1, color)
        self.rect(x0, y0, x0 + t, y1, color)
        self.rect(x1 - t, y0, x1, y1, color)

    def ellipse(self, cx, cy, rx, ry, color):
        if rx <= 0 or ry <= 0:
            return
        for dy in range(-ry, ry + 1):
            span = int(rx * ((1.0 - (dy / ry) ** 2) ** 0.5))
            self.rect(cx - span, cy + dy, cx + span + 1, cy + dy + 1, color)

    def circle(self, cx, cy, r, color):
        self.ellipse(cx, cy, r, r, color)

    def line(self, x0, y0, x1, y1, color, t=1):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        r = max(0, t // 2)
        for s in range(steps + 1):
            x = round(x0 + (x1 - x0) * s / steps)
            y = round(y0 + (y1 - y0) * s / steps)
            if r == 0:
                self.set(x, y, color)
            else:
                self.circle(x, y, r, color)

    def polygon(self, pts, color):
        ys = [p[1] for p in pts]
        for y in range(min(ys), max(ys) + 1):
            nodes = []
            n = len(pts)
            for i in range(n):
                xa, ya = pts[i]
                xb, yb = pts[(i + 1) % n]
                if (ya <= y < yb) or (yb <= y < ya):
                    nodes.append(xa + (y - ya) * (xb - xa) / (yb - ya))
            nodes.sort()
            for i in range(0, len(nodes) - 1, 2):
                self.rect(int(nodes[i]), y, int(nodes[i + 1]) + 1, y + 1, color)

    def text(self, x, y_baseline, s, font, color, tracking=0.0):
        pen = float(x)
        for ch in s:
            glyph = font.glyphs.get(ord(ch))
            if glyph is None:
                continue
            if glyph.w and glyph.h:
                self._blit(pen + glyph.left, y_baseline + glyph.top, glyph, color)
            pen += glyph.advance + tracking
        return pen

    def _blit(self, gx, gy, glyph, color):
        gx = int(round(gx))
        gy = int(round(gy))
        data = glyph.data
        idx = 0
        for row in range(glyph.h):
            y = gy + row
            if not (0 <= y < self.h):
                idx += glyph.w
                continue
            for col in range(glyph.w):
                byte = data[idx >> 1]
                cov = (byte >> 4) if idx % 2 == 0 else (byte & 0x0F)
                idx += 1
                if cov:
                    self.blend(gx + col, y, color, cov)

    def text_centered(self, cx, y_baseline, s, font, color, tracking=0.0):
        width = font.text_width(s, tracking)
        return self.text(cx - width / 2, y_baseline, s, font, color, tracking)

    def text_right(self, x_right, y_baseline, s, font, color, tracking=0.0):
        width = font.text_width(s, tracking)
        return self.text(x_right - width, y_baseline, s, font, color, tracking)


def png_bytes(canvas):
    """Encode the framebuffer as a PNG with fixed, deterministic chunks."""
    w, h = canvas.w, canvas.h
    stride = w * 3
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += canvas.px[y * stride:(y + 1) * stride]
    compressed = zlib.compress(bytes(raw), 6)

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">I I B B B B B", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------- icons
# Each icon draws inside the square box (x, y, size). bg is the colour of
# the surface behind the icon, used for cut-out details.

def icon_drone(cv, x, y, s, bg):
    cx, cy = x + s // 2, y + s // 2
    rotors = [(x + int(0.20 * s), y + int(0.24 * s)),
              (x + int(0.80 * s), y + int(0.24 * s)),
              (x + int(0.20 * s), y + int(0.76 * s)),
              (x + int(0.80 * s), y + int(0.76 * s))]
    for rx, ry in rotors:
        cv.line(rx, ry, cx, cy, INK, t=max(3, s // 22))
    for rx, ry in rotors:
        cv.ellipse(rx, ry, int(0.17 * s), max(2, int(0.05 * s)), INK)
        cv.circle(rx, ry, max(2, s // 40), bg)
    cv.rect(cx - int(0.15 * s), cy - int(0.11 * s),
            cx + int(0.15 * s), cy + int(0.11 * s), INK)
    cv.line(cx, cy + int(0.11 * s), cx, cy + int(0.24 * s), INK,
            t=max(3, s // 26))
    cv.circle(cx, cy + int(0.30 * s), max(3, int(0.055 * s)), RED)



# ---------------------------------------------------------------- world map
# A coarse dot-matrix world: land spans per row on a 118 x 28 grid.
# Column c sits at longitude -170 + 3.05c degrees; row r at latitude
# 75 - 4.5r degrees. Abstract on purpose — pins carry the precision.

MAP_ROWS = 28
MAP_COLS = 118
MAP_SPANS = {
    0: [(13, 16), (21, 24), (44, 46), (70, 75), (85, 89), (99, 103)],
    1: [(4, 8), (13, 35), (44, 49), (58, 61), (68, 110)],
    2: [(2, 9), (11, 37), (43, 49), (57, 63), (65, 112)],
    3: [(3, 8), (13, 39), (45, 48), (57, 62), (64, 112)],
    4: [(4, 5), (15, 37), (55, 55), (57, 65), (71, 73), (75, 104)],
    5: [(14, 36), (55, 56), (57, 66), (72, 99)],
    6: [(13, 35), (55, 65), (68, 72), (76, 99), (101, 102)],
    7: [(13, 34), (55, 62), (64, 71), (80, 96), (99, 101)],
    8: [(13, 33), (55, 57), (60, 61), (63, 63), (64, 78), (82, 96),
        (98, 100)],
    9: [(13, 26), (55, 68), (67, 72), (73, 81), (84, 93)],
    10: [(13, 20), (24, 25), (54, 70), (66, 72), (76, 80), (85, 93)],
    11: [(14, 19), (54, 69), (76, 79), (85, 89), (92, 92), (94, 94)],
    12: [(15, 18), (54, 68), (77, 78), (85, 88), (92, 93)],
    13: [(25, 30), (55, 67), (68, 70), (85, 88), (90, 91), (93, 94),
         (96, 97), (100, 103)],
    14: [(24, 34), (56, 66), (67, 69), (86, 88), (90, 91), (93, 94),
         (96, 96), (101, 103)],
    15: [(25, 35), (58, 66), (66, 68), (88, 90), (92, 93), (95, 95)],
    16: [(27, 36), (58, 65), (90, 94), (95, 102)],
    17: [(26, 35), (59, 66)],
    18: [(4, 4), (28, 35), (59, 65), (93, 95), (100, 102)],
    19: [(29, 34), (60, 65), (92, 103)],
    20: [(28, 33), (60, 64), (69, 70), (91, 104)],
    21: [(29, 33), (60, 64), (69, 70), (92, 103)],
    22: [(28, 31), (60, 63), (69, 69), (93, 101)],
    23: [(28, 30), (60, 63), (94, 99), (109, 110)],
    24: [(27, 29), (95, 98), (109, 111)],
    25: [(27, 29), (108, 109)],
    26: [(27, 28)],
    27: [(27, 28)],
}

# Numbered pins for the 13 main stories: story -> (column, row).
PINS = {
    1: (71, 10),    # Kuwait / Bahrain
    2: (93, 11),    # Shenzhen
    3: (7, 2),      # Alaska
    4: (68, 7),     # Kerch Bridge, Crimea
    5: (63, 17),    # DR Congo
    6: (24, 8),     # United States (measles)
    7: (16, 8),     # California (Nvidia)
    8: (109, 25),   # New Zealand (GTA VI launch)
    9: (4, 18),     # Northern Cook Islands (Cyclone Xavier)
    10: (31, 8),    # New York (Wall Street)
    11: (66, 8),    # Antalya, Turkey (COP31)
    12: (56, 5),    # London (UK inflation)
    13: (84, 5),    # Kemerovo, Siberia (plane crash)
}


def draw_world_map(cv, fonts, x0, y0):
    """Dot-matrix world with numbered pins for the main stories."""
    for r, spans in MAP_SPANS.items():
        for c0, c1 in spans:
            for c in range(c0, c1 + 1):
                cv.circle(x0 + c * 8, y0 + r * 5, 2, DOTO)
    num_font = fonts["bold10"]
    for story, (c, r) in PINS.items():
        cx, cy = x0 + c * 8, y0 + r * 5
        cv.circle(cx, cy, 9, RED)
        label = str(story)
        w = num_font.text_width(label)
        cv.text(cx - w / 2, cy + 3, label, num_font, PANEL)


# ---------------------------------------------------------------- panel art
# Each lead panel carries a simple drawn scene in a 296 x 64 strip.

def art_gulf(cv, fonts, x, y, w, h):
    """Schematic map of the northern Gulf: Iran above, Arabia below."""
    cv.rect(x, y, x + w, y + h, SEA)
    # Iran (top right landmass)
    cv.polygon([(x + 118, y), (x + w, y), (x + w, y + 26),
                (x + 232, y + 34), (x + 176, y + 26), (x + 138, y + 12)],
               LAND)
    # Arabia (bottom left landmass)
    cv.polygon([(x, y + h), (x, y + 30), (x + 44, y + 24),
                (x + 104, y + 34), (x + 138, y + 46), (x + 128, y + h)],
               LAND)
    lab = fonts["reg10"]
    cv.text(x + 216, y + 14, "IRAN", lab, INK, tracking=1.0)
    cv.text(x + 18, y + 52, "KUWAIT", lab, INK, tracking=0.5)
    cv.text(x + 88, y + 60, "BAHRAIN", lab, INK, tracking=0.5)
    # Qeshm Island, struck by US jets; drone targets in Kuwait and Bahrain.
    cv.circle(x + 158, y + 22, 4, INK)
    cv.text(x + 166, y + 26, "Qeshm I.", lab, INK)
    for tx, ty in ((x + 96, y + 33), (x + 122, y + 41)):
        cv.circle(tx, ty, 6, RED)
        cv.circle(tx, ty, 2, PANEL)
    cv.line(x + 154, y + 24, x + 100, y + 31, RED, t=2)
    cv.line(x + 154, y + 24, x + 126, y + 39, RED, t=2)
    icon_drone(cv, x + w - 52, y + 6, 40, SEA)


def art_skyline(cv, fonts, x, y, w, h):
    """Shenzhen skyline silhouette under a red sun."""
    cv.rect(x, y, x + w, y + h, SAND)
    cv.circle(x + 52, y + 20, 13, RED)
    base = y + h
    towers = [(0, 30), (26, 44), (52, 24), (74, 52), (104, 36), (128, 58),
              (160, 30), (184, 46), (212, 26), (234, 40), (262, 32),
              (284, 48)]
    for tx, th in towers:
        cv.rect(x + tx, base - th, x + tx + 20, base, SLATE)
    cv.rect(x + 128, base - 58, x + 148, base - 52, SLATE)
    cv.text_right(x + w - 8, y + 16, "SHENZHEN", fonts["reg10"], INK,
                  tracking=1.0)


def art_senate(cv, fonts, x, y, w, h):
    """Senate seat bars after the Alaska call: Democrats 56, Republicans 44."""
    cv.rect(x, y, x + w, y + h, SAND)
    lab = fonts["bold12"]
    num = fonts["bold14"]
    cv.text(x + 10, y + 24, "DEM", lab, BLUE)
    cv.rect(x + 52, y + 12, x + 52 + 196, y + 26, BLUE)
    cv.text(x + 256, y + 25, "56", num, BLUE)
    cv.text(x + 10, y + 52, "REP", lab, RED)
    cv.rect(x + 52, y + 40, x + 52 + 154, y + 54, RED)
    cv.text(x + 256, y + 53, "44", num, RED)



# ---------------------------------------------------------------- content
# Every story below was reported on Wednesday 18 November 2026; see
# SOURCES.md for the outlet behind each one.

LEADS = [
    ("MIDDLE EAST · GULF CONFLICT", RED,
     "Kuwait, Bahrain say they downed Iranian drones",
     "Iran's army sent combat drones at US bases in Kuwait and Bahrain "
     "after US jets struck an IRGC missile site on Qeshm Island.",
     art_gulf),
    ("ASIA · DIPLOMACY", BROWN,
     "Xi opens APEC summit in Shenzhen",
     "Xi pledges free trade as Putin speaks and Trump lands for "
     "Thursday's three-way summit with the US and Russian leaders.",
     art_skyline),
    ("AMERICAS · US POLITICS", BLUE,
     "Peltola wins Alaska; Senate 56–44",
     "AP calls the last Senate race for Democrat Mary Peltola: nine "
     "flips, the most in a midterm since 1958.",
     art_senate),
]

# Stories 4-13, in reading order.
GRID = [
    ("EUROPE · UKRAINE", RED,
     "Ukraine wrecks Crimea bridge span",
     "Kerch road deck destroyed; Kyiv downs 126 of 141 drones."),
    ("AFRICA · HEALTH", GREEN,
     "Congo Ebola tops 11,000 cases",
     "Doubled in three months; 5,400 dead, children hit hardest."),
    ("HEALTH · AMERICAS", TEAL,
     "US loses measles-free status",
     "Status held since 2000 ends after 5,400 cases, 10 deaths."),
    ("BUSINESS · TECH", PLUM,
     "Nvidia revenue doubles to $115.8bn",
     "Sales beat forecasts; guidance $130bn; Huang return barred."),
    ("CULTURE · GAMING", PLUM,
     "GTA VI arrives after a 13-year wait",
     "Midnight launches roll out worldwide, first in New Zealand."),
    ("OCEANIA · WEATHER", TEAL,
     "Cyclone Xavier reaches Category 5",
     "Winds of 220 km/h near the Northern Cook Islands."),
    ("MARKETS · US", BLUE,
     "Dow sinks 849 points in tech slide",
     "S&P 500 at lowest close since July; fourth straight fall."),
    ("CLIMATE · COP31", GREEN,
     "COP31 talks split over fossil fuels",
     "Draft text divides Antalya talks on fuels and funding."),
    ("EUROPE · ECONOMY", BROWN,
     "UK inflation rises to 3.6%",
     "Highest in a year as transport and fuel costs climb — ONS."),
    ("RUSSIA · DISASTER", SLATE,
     "Russian transport plane crash kills 19",
     "An-12 comes down in the Kemerovo region of Siberia."),
]

# Stories 14-38: one line each.
BRIEFS = [
    "Magnitude 6.0 earthquake strikes Papua New Guinea",
    "Magnitude 5.3 earthquake rattles Romania overnight",
    "UN: winter cold endangers Gaza's displaced in tents",
    "UN: drones killed 1,600+ people in Sudan this year",
    "UNHCR: 2,500 dead or missing on sea routes to Europe",
    "Five EU states plan migrant return hubs in Rwanda",
    "Knesset elects Kahana as speaker, 66 to 52",
    "UK, Australia sanction West Bank settler groups",
    "Qatar condemns Iran's drone strikes on neighbours",
    "Quad leaders meet in Manila on AI, sea security",
    "India, Japan open 2+2 defence talks in Tokyo",
    "South Korea hushes flights for college exam day",
    "Malaysia's economy grows 5.5% in third quarter",
    "Isolated Awa group emerges in Brazil's Amazon",
    "Nigeria approves law for state-run police forces",
    "Ghana's $60m presidential jet sparks outrage",
    "NSA outage was maintenance, not an attack — Rubio",
    "Oil slips as US crude stockpiles build",
    "M-class solar flare erupts from the Sun",
    "Jordan beat Australia 2-0 in Doha friendly",
    "India edge Pakistan 2-1 to win SAFF title",
    "Celtic beat Dundee 2-1 after extra time in cup",
    "Watkins gives Aston Villa 1-0 win at Brentford",
    "Kenya's Ruto gives State of the Nation address",
    "Johannesburg to restrict water from this weekend",
]

STORY_COUNT = len(LEADS) + len(GRID) + len(BRIEFS)  # 38


# ---------------------------------------------------------------- layout

MARGIN = 22
RIGHT = PAGE_W - MARGIN  # 1002
CONTENT_W = RIGHT - MARGIN  # 980


def draw_lead_panel(cv, fonts, x, y, w, h, kicker, color, headline, deck,
                    art):
    cv.rect(x, y, x + w, y + h, PANEL)
    cv.frame(x, y, x + w, y + h, BORDER, t=1)
    cv.rect(x, y, x + w, y + 4, color)
    art(cv, fonts, x + 12, y + 12, w - 24, 62)
    cv.text(x + 12, y + 96, kicker, fonts["bold12"], color, tracking=1.0)
    head_font = fonts["bold24"]
    base = y + 124
    for line in head_font.wrap(headline, w - 24):
        cv.text(x + 12, base, line, head_font, INK)
        base += 27
    deck_font = fonts["reg14"]
    base = y + 168
    for line in deck_font.wrap(deck, w - 24)[:3]:
        cv.text(x + 12, base, line, deck_font, DECK)
        base += 17


def draw_grid_cell(cv, fonts, x, y, w, h, num, kicker, color, headline,
                   deck):
    cv.rect(x, y, x + w, y + h, PANEL)
    cv.frame(x, y, x + w, y + h, BORDER, t=1)
    cv.rect(x, y, x + w, y + 3, color)
    # Number badge + kicker.
    cv.rect(x + 7, y + 8, x + 24, y + 25, RED)
    nf = fonts["bold10"]
    label = str(num)
    cv.text(x + 15.5 - nf.text_width(label) / 2, y + 20, label, nf, PANEL)
    cv.text(x + 30, y + 21, kicker, fonts["bold11"], color, tracking=0.5)
    head_font = fonts["bold17"]
    base = y + 47
    for line in head_font.wrap(headline, w - 14)[:3]:
        cv.text(x + 7, base, line, head_font, INK)
        base += 19
    deck_font = fonts["reg11"]
    base += 6
    for line in deck_font.wrap(deck, w - 14)[:2]:
        cv.text(x + 7, base, line, deck_font, DECK)
        base += 13


def draw_briefs(cv, fonts, x, y):
    """Three columns of numbered one-line briefs, stories 14-38."""
    cols = [BRIEFS[:9], BRIEFS[9:17], BRIEFS[17:]]
    starts = [14, 23, 31]
    col_x = [x, x + 332, x + 664]
    num_font = fonts["bold12"]
    text_font = fonts["reg11"]
    for col, start, cx in zip(cols, starts, col_x):
        base = y
        for i, brief in enumerate(col):
            label = str(start + i) + "."
            cv.text(cx, base, label, num_font, RED)
            cv.text(cx + 24, base, brief, text_font, DECK)
            base += 18


def build_page(fonts):
    cv = Canvas(PAGE_W, PAGE_H, PAPER)

    # Masthead strip: name left, the day's tally right.
    cv.text(MARGIN, 30, "THE DAY IN WORLD NEWS", fonts["bold20"], INK,
            tracking=1.5)
    cv.text_right(RIGHT, 30,
                  f"{STORY_COUNT} STORIES · 6 CONTINENTS · ONE DAY",
                  fonts["bold14"], RED, tracking=1.0)
    cv.rect(MARGIN, 38, RIGHT, 41, INK)

    # The date, as large as the page allows.
    date_font = fonts["bold60"]
    cv.text_centered(PAGE_W // 2, 102, "Wednesday 18 November 2026",
                     date_font, INK, tracking=1.0)
    cv.rect(MARGIN, 112, RIGHT, 115, RED)

    # Three lead panels.
    panel_y, panel_h, panel_w = 124, 216, 320
    for i, (kicker, color, headline, deck, art) in enumerate(LEADS):
        draw_lead_panel(cv, fonts, MARGIN + i * (panel_w + 10), panel_y,
                        panel_w, panel_h, kicker, color, headline, deck, art)

    # Numbered grid, stories 4-13 (two rows of five).
    cell_w, cell_h = 188, 118
    for i, (kicker, color, headline, deck) in enumerate(GRID):
        cx = MARGIN + (i % 5) * (cell_w + 10)
        cy = 352 + (i // 5) * (cell_h + 10)
        draw_grid_cell(cv, fonts, cx, cy, cell_w, cell_h, i + 4,
                       kicker, color, headline, deck)

    # World map band.
    map_head_y = 622
    cv.text(MARGIN, map_head_y, "WHERE IT HAPPENED", fonts["bold14"], INK,
            tracking=1.5)
    cv.text_right(RIGHT, map_head_y,
                  "AMERICAS · EUROPE · AFRICA · MIDDLE EAST · ASIA · "
                  "OCEANIA · GLOBAL",
                  fonts["reg10"], FAINT, tracking=0.5)
    draw_world_map(cv, fonts, MARGIN + 18, map_head_y + 14)

    # Briefs.
    briefs_head_y = 800
    cv.rect(MARGIN, briefs_head_y - 14, RIGHT, briefs_head_y - 12, INK)
    cv.text(MARGIN, briefs_head_y + 8, "ALSO ON WEDNESDAY 18 NOVEMBER",
            fonts["bold14"], INK, tracking=1.5)
    cv.text_right(RIGHT, briefs_head_y + 8, "STORIES 14–38",
                  fonts["reg11"], FAINT)
    draw_briefs(cv, fonts, MARGIN, briefs_head_y + 34)

    # Footer.
    cv.rect(MARGIN, 984, RIGHT, 985, INK)
    cv.text(MARGIN, 1006,
            "Every story was reported on Wednesday 18 November 2026",
            fonts["reg11"], FAINT)
    cv.text_right(RIGHT, 1006,
                  "Sources: Reuters · AP · BBC · AFP · Al Jazeera · "
                  "UN News · The Guardian · MetService · PANA · ONS",
                  fonts["reg11"], FAINT)
    return cv


def main():
    fonts = load_fonts()
    canvas = build_page(fonts)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "entry.png")
    with open(out_path, "wb") as fh:
        fh.write(png_bytes(canvas))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
