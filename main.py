#!/usr/bin/env python3
"""THE DAY IN WORLD NEWS -- Wednesday 18 November 2026.

Draws a one-page newspaper front page (1024x1024 PNG) summing up the
day's world news, using only the Python standard library.  Glyphs come
pre-rasterised in fonts.bin (see gen_fonts.py, a build-time tool).
Deterministic: no randomness, no clock, no network.
"""
import os
import struct
import sys
import zlib

# ---------------------------------------------------------------- fonts

EXTRA = "£·á–—‘’“”…×"
CHARSET = "".join(chr(c) for c in range(32, 127)) + EXTRA
FONT_NAMES = [
    "bold60", "bold24", "bold20", "bold17", "bold14", "bold12",
    "bold11", "bold10", "reg14", "reg11", "reg10",
]
MAGIC = b"FNT1"


def load_fonts(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:4] != MAGIC:
        raise ValueError("bad fonts.bin magic")
    data = zlib.decompress(raw[4:])
    pos = 0
    (nfonts,) = struct.unpack_from("<B", data, pos)
    pos += 1
    fonts = {}
    for fi in range(nfonts):
        (count,) = struct.unpack_from("<H", data, pos)
        pos += 2
        glyphs = {}
        for ci in range(count):
            adv, x0, y0, w, h = struct.unpack_from("<BhhBB", data, pos)
            pos += 7
            nbytes = (w * h + 1) // 2
            packed = data[pos:pos + nbytes]
            pos += nbytes
            glyphs[CHARSET[ci]] = (adv, x0, y0, w, h, packed)
        fonts[FONT_NAMES[fi]] = glyphs
    return fonts


FONTS = None  # set in main()


def text_width(font, text, tracking=0):
    glyphs = FONTS[font]
    total = 0
    for ch in text:
        g = glyphs.get(ch)
        if g is None:
            g = glyphs["?"]
        total += g[0] + tracking
    if text:
        total -= tracking
    return total


def wrap_text(font, text, max_width):
    """Greedy word wrap; returns a list of lines that fit max_width."""
    words = text.split()
    lines = []
    cur = ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if text_width(font, trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- canvas

class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(bg) * (w * h)

    def _set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i] = color[0]
            self.px[i + 1] = color[1]
            self.px[i + 2] = color[2]

    def _blend(self, x, y, color, cov):
        # cov is 0..15 glyph coverage
        if cov == 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = (y * self.w + x) * 3
        if cov == 15:
            self.px[i] = color[0]
            self.px[i + 1] = color[1]
            self.px[i + 2] = color[2]
        else:
            inv = 15 - cov
            self.px[i] = (self.px[i] * inv + color[0] * cov) // 15
            self.px[i + 1] = (self.px[i + 1] * inv + color[1] * cov) // 15
            self.px[i + 2] = (self.px[i + 2] * inv + color[2] * cov) // 15

    def rect(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def frame(self, x, y, w, h, color, t=1):
        self.rect(x, y, w, t, color)
        self.rect(x, y + h - t, w, t, color)
        self.rect(x, y, t, h, color)
        self.rect(x + w - t, y, t, h, color)

    def circle(self, cx, cy, r, color):
        for yy in range(cy - r, cy + r + 1):
            dy = yy - cy
            rem = r * r - dy * dy
            if rem < 0:
                continue
            dx = int(rem ** 0.5)
            self.rect(cx - dx, yy, dx * 2 + 1, 1, color)

    def ring(self, cx, cy, r, color, t=2):
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                d2 = (xx - cx) ** 2 + (yy - cy) ** 2
                if (r - t) ** 2 <= d2 <= r * r:
                    self._set(xx, yy, color)

    def ellipse(self, cx, cy, rx, ry, color):
        if rx <= 0 or ry <= 0:
            return
        for yy in range(cy - ry, cy + ry + 1):
            dy = (yy - cy) / ry
            rem = 1.0 - dy * dy
            if rem < 0:
                continue
            dx = int(rx * (rem ** 0.5))
            self.rect(cx - dx, yy, dx * 2 + 1, 1, color)

    def line(self, x0, y0, x1, y1, color, t=1):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        half = t // 2
        while True:
            self.rect(x0 - half, y0 - half, t, t, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def polygon(self, points, color):
        ys = [p[1] for p in points]
        y_lo = max(0, min(ys))
        y_hi = min(self.h - 1, max(ys))
        n = len(points)
        for yy in range(y_lo, y_hi + 1):
            nodes = []
            for i in range(n):
                xa, ya = points[i]
                xb, yb = points[(i + 1) % n]
                if (ya <= yy < yb) or (yb <= yy < ya):
                    nodes.append(xa + (yy - ya) * (xb - xa) / (yb - ya))
            nodes.sort()
            for i in range(0, len(nodes) - 1, 2):
                xa = int(nodes[i])
                xb = int(nodes[i + 1])
                self.rect(xa, yy, xb - xa + 1, 1, color)

    # ------------------------------------------------------------ text
    def text(self, font, x, y, s, color, tracking=0):
        glyphs = FONTS[font]
        cx = x
        for ch in s:
            g = glyphs.get(ch)
            if g is None:
                g = glyphs["?"]
            adv, x0, y0, w, h, packed = g
            if w and h:
                idx = 0
                for yy in range(h):
                    for xx in range(w):
                        byte = packed[idx >> 1]
                        cov = (byte >> 4) if (idx & 1) == 0 else (byte & 15)
                        idx += 1
                        if cov:
                            self._blend(cx + x0 + xx, y + y0 + yy, color, cov)
            cx += adv + tracking
        return cx - x - (tracking if s else 0)

    def text_centered(self, font, cx, y, s, color, tracking=0):
        w = text_width(font, s, tracking)
        return self.text(font, cx - w // 2, y, s, color, tracking)

    def text_right(self, font, x_right, y, s, color, tracking=0):
        w = text_width(font, s, tracking)
        return self.text(font, x_right - w, y, s, color, tracking)


# ---------------------------------------------------------------- png

def write_png(canvas, path):
    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    raw = bytearray()
    stride = canvas.w * 3
    for yy in range(canvas.h):
        raw.append(0)
        raw += canvas.px[yy * stride:(yy + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", canvas.w, canvas.h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    return len(png)


# ---------------------------------------------------------------- content

PAPER = (247, 243, 234)
PANEL = (253, 251, 246)
INK = (22, 24, 29)
BODY = (48, 50, 56)
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
MAPDOT = (168, 156, 128)
WHITE = (255, 255, 255)

MARGIN = 22
WIDTH = 980

LEADS = [
    ("MIDDLE EAST · GULF CONFLICT", RED,
     "Kuwait, Bahrain say they downed Iranian drones",
     "Iran's army sent combat drones at US bases in Kuwait and Bahrain "
     "after US jets struck an IRGC missile site on Qeshm Island.", "gulf"),
    ("ASIA · DIPLOMACY", BROWN,
     "Xi opens APEC summit in Shenzhen",
     "Xi pledges free trade as Putin speaks and Trump lands for "
     "Thursday's three-way summit with the US and Russian leaders.", "sky"),
    ("AMERICAS · US POLITICS", BLUE,
     "Peltola wins Alaska; Senate 56–44",
     "AP calls the last Senate race for Democrat Mary Peltola: nine "
     "flips, the most in a midterm since 1958.", "senate"),
]

GRID = [
    ("EUROPE · UKRAINE", RED, "Ukraine wrecks Crimea bridge span",
     "Kerch road deck destroyed; Kyiv downs 126 of 141 drones."),
    ("AFRICA · HEALTH", GREEN, "Congo Ebola tops 11,000 cases",
     "Doubled in three months; 5,400 dead, children hit hardest."),
    ("HEALTH · AMERICAS", TEAL, "US loses measles-free status",
     "Status held since 2000 ends after 5,400 cases, 10 deaths."),
    ("BUSINESS · TECH", PLUM, "Nvidia revenue doubles to $115.8bn",
     "Sales beat forecasts; guidance $130bn; Huang return barred."),
    ("CULTURE · GAMING", PLUM, "GTA VI arrives after a 13-year wait",
     "Midnight launches roll out worldwide, first in New Zealand."),
    ("OCEANIA · WEATHER", TEAL, "Cyclone Xavier reaches Category 5",
     "Winds of 220 km/h near the Northern Cook Islands."),
    ("MARKETS · US", BLUE, "Dow sinks 849 points in tech slide",
     "S&P 500 at lowest close since July; fourth straight fall."),
    ("CLIMATE · COP31", GREEN, "COP31 talks split over fossil fuels",
     "Draft text divides Antalya talks on fuels and funding."),
    ("EUROPE · ECONOMY", BROWN, "UK inflation rises to 3.6%",
     "Highest in a year as transport and fuel costs climb — ONS."),
    ("RUSSIA · DISASTER", SLATE, "Russian transport plane crash kills 19",
     "An-12 comes down in the Kemerovo region of Siberia."),
]

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

# ---------------------------------------------------------------- lead art

def art_gulf(cv, x, y, w, h):
    cv.rect(x, y, w, h, SEA)
    # Iran: landmass across the top-right
    cv.polygon([(x + 120, y), (x + w, y), (x + w, y + 26),
                (x + 210, y + 30), (x + 160, y + 14)], LAND)
    cv.text("bold10", x + w - 52, y + 4, "IRAN", INK)
    # Kuwait / Bahrain: bottom-left shore
    cv.polygon([(x, y + h), (x, y + 34), (x + 52, y + 40),
                (x + 88, y + h)], LAND)
    cv.text("bold10", x + 4, y + h - 26, "KUWAIT", INK)
    cv.text("bold10", x + 4, y + h - 13, "BAHRAIN", INK)
    # Qeshm Island dot, mid-map
    qx, qy = x + 196, y + 22
    cv.circle(qx, qy, 3, INK)
    cv.text("bold10", qx + 7, qy - 5, "Qeshm I.", BODY)
    # targets: red-ringed circles lower-right and centre-right
    for tx, ty in ((x + 96, y + 46), (x + 238, y + 48)):
        cv.ring(tx, ty, 6, RED, 2)
        cv.circle(tx, ty, 2, RED)
        cv.line(qx, qy, tx, ty, RED, 1)
    # drone icon top-right: X arms, rotors, body
    dx, dy = x + w - 34, y + 40
    cv.line(dx - 11, dy - 8, dx + 11, dy + 8, INK, 2)
    cv.line(dx - 11, dy + 8, dx + 11, dy - 8, INK, 2)
    cv.ellipse(dx - 13, dy - 10, 6, 2, INK)
    cv.ellipse(dx + 13, dy - 10, 6, 2, INK)
    cv.ellipse(dx - 13, dy + 10, 6, 2, INK)
    cv.ellipse(dx + 13, dy + 10, 6, 2, INK)
    cv.circle(dx, dy, 4, RED)


def art_skyline(cv, x, y, w, h):
    cv.rect(x, y, w, h, SAND)
    cv.circle(x + 40, y + 16, 11, RED)
    base = y + h
    towers = [(0, 30, 16), (20, 44, 14), (38, 24, 18), (60, 52, 15),
              (79, 36, 13), (96, 58, 17), (117, 28, 14), (135, 46, 16),
              (155, 33, 13), (172, 55, 18), (194, 26, 14), (212, 42, 15),
              (231, 31, 13), (248, 50, 16), (268, 35, 14)]
    for tx, th, tw in towers:
        if x + tx + tw <= x + w:
            cv.rect(x + tx, base - th, tw, th, SLATE)
    cv.rect(x, base - 2, w, 2, INK)
    cv.rect(x + w - 72, y + 2, 68, 13, SAND)
    cv.text_right("bold10", x + w - 4, y + 3, "SHENZHEN", INK)


def art_senate(cv, x, y, w, h):
    cv.rect(x, y, w, h, SAND)
    # DEM bar: length proportional to 56, REP to 44 (scale 3.4 px/seat)
    cv.text("bold11", x + 10, y + 10, "DEM", BLUE)
    cv.rect(x + 48, y + 8, int(56 * 3.4), 15, BLUE)
    cv.text("bold11", x + 48 + int(56 * 3.4) + 6, y + 10, "56", INK)
    cv.text("bold11", x + 10, y + 36, "REP", RED)
    cv.rect(x + 48, y + 34, int(44 * 3.4), 15, RED)
    cv.text("bold11", x + 48 + int(44 * 3.4) + 6, y + 36, "44", INK)


ART = {"gulf": art_gulf, "sky": art_skyline, "senate": art_senate}

# ---------------------------------------------------------------- sections

def masthead_and_date(cv):
    cv.text("bold20", MARGIN, 8, "THE DAY IN WORLD NEWS", INK, tracking=3)
    cv.text_right("bold14", MARGIN + WIDTH, 13,
                  "38 STORIES · 6 CONTINENTS · ONE DAY", RED)
    cv.rect(MARGIN, 38, WIDTH, 3, INK)
    cv.text_centered("bold60", MARGIN + WIDTH // 2, 48,
                     "Wednesday 18 November 2026", INK)
    cv.rect(MARGIN, 112, WIDTH, 3, RED)


def lead_panels(cv):
    y = 124
    w, h, gap = 320, 216, 10
    for i, (kicker, colour, head, deck, art) in enumerate(LEADS):
        x = MARGIN + i * (w + gap)
        cv.rect(x, y, w, h, PANEL)
        cv.frame(x, y, w, h, BORDER, 1)
        cv.rect(x, y, w, 4, colour)
        ART[art](cv, x + 12, y + 12, w - 24, 62)
        cv.text("bold12", x + 12, y + 84, kicker, colour)
        lines = wrap_text("bold24", head, w - 24)
        ly = y + 104
        for ln in lines[:3]:
            cv.text("bold24", x + 12, ly, ln, INK)
            ly += 27
        dy = y + 158
        for ln in wrap_text("reg14", deck, w - 24)[:3]:
            cv.text("reg14", x + 12, dy, ln, BODY)
            dy += 17


def story_grid(cv):
    cw, ch, gap = 188, 118, 10
    for idx, (kicker, colour, head, deck) in enumerate(GRID):
        row, col = divmod(idx, 5)
        x = MARGIN + col * (cw + gap)
        y = 352 + row * (ch + gap)
        cv.rect(x, y, cw, ch, PANEL)
        cv.frame(x, y, cw, ch, BORDER, 1)
        cv.rect(x, y, cw, 3, colour)
        # number badge
        cv.rect(x + 8, y + 9, 16, 16, RED)
        num = str(idx + 4)
        nw = text_width("bold10", num)
        cv.text("bold10", x + 8 + (16 - nw) // 2, y + 12, num, WHITE)
        cv.text("bold11", x + 30, y + 11, kicker, colour)
        ly = y + 32
        for ln in wrap_text("bold17", head, cw - 16)[:3]:
            cv.text("bold17", x + 8, ly, ln, INK)
            ly += 19
        dy = y + 90
        for ln in wrap_text("reg11", deck, cw - 16)[:2]:
            cv.text("reg11", x + 8, dy, ln, BODY)
            dy += 13


# ---------------------------------------------------------------- map

def _in(lon, lat, lon0, lon1, lat0, lat1):
    return lon0 <= lon <= lon1 and lat0 <= lat <= lat1


def is_land(lon, lat):
    # North America
    if _in(lon, lat, -168, -140, 55, 70):
        return True
    if _in(lon, lat, -140, -60, 42, 72) and lat < 68 - (lon + 60) * 0.05:
        return True
    if _in(lon, lat, -125, -67, 25, 49):
        return True
    if _in(lon, lat, -117, -87, 14, 32) and lat > 10 + (lon + 117) * 0.12:
        return True
    if _in(lon, lat, -92, -77, 7, 18):
        return True
    # Greenland
    if _in(lon, lat, -58, -20, 60, 82) and lat < 84 - abs(lon + 39) * 0.35:
        return True
    # South America
    if _in(lon, lat, -77, -35, -5, 10):
        return True
    if _in(lon, lat, -70, -40, -20, -5):
        return True
    if _in(lon, lat, -73, -55, -40, -20) and lon < -55 - (lat + 40) * 0.4:
        return True
    if _in(lon, lat, -73, -67, -55, -40):
        return True
    # Europe
    if _in(lon, lat, -9, 3, 36, 44):
        return True
    if _in(lon, lat, -5, 30, 45, 55):
        return True
    if _in(lon, lat, 5, 31, 55, 70) and lat < 72 - abs(lon - 18) * 0.25:
        return True
    if _in(lon, lat, 30, 45, 45, 65):
        return True
    # Africa
    if _in(lon, lat, -17, 32, 15, 35):
        return True
    if _in(lon, lat, -17, 20, 4, 15):
        return True
    if _in(lon, lat, 8, 42, -5, 5):
        return True
    if _in(lon, lat, 12, 35, -35, -5) and lon < 38 + lat * 0.35:
        return True
    if _in(lon, lat, 43, 50, -25, -12):
        return True
    # Asia
    if _in(lon, lat, 35, 63, 12, 42):
        return True
    if _in(lon, lat, 45, 90, 35, 55):
        return True
    if _in(lon, lat, 60, 178, 50, 75) and lat < 78 - (lon - 60) * 0.06:
        return True
    if _in(lon, lat, 68, 89, 8, 35) and lat > 4 + abs(lon - 78) * 0.9:
        return True
    if _in(lon, lat, 92, 108, 5, 28):
        return True
    if _in(lon, lat, 75, 135, 18, 53):
        return True
    if _in(lon, lat, 126, 142, 31, 45) and (lon + lat) % 3 != 0:
        return True
    if _in(lon, lat, 95, 141, -10, 5) and (int(lon) % 4 != 0):
        return True
    # Oceania
    if _in(lon, lat, 113, 142, -22, -11):
        return True
    if _in(lon, lat, 115, 150, -39, -25):
        return True
    if _in(lon, lat, 131, 147, -9, -1):
        return True
    if _in(lon, lat, 167, 178, -46, -34) and abs((lon - 167) - (-lat - 34)) < 4:
        return True
    return False


PINS = [
    (1, 47.5, 29.0),     # Kuwait / Bahrain
    (2, 114.0, 22.5),    # Shenzhen
    (3, -150.0, 64.0),   # Alaska
    (4, 36.6, 45.0),     # Kerch / Crimea
    (5, 23.0, -3.0),     # DR Congo
    (6, -98.0, 39.0),    # USA, measles
    (7, -120.0, 37.0),   # California
    (8, 172.0, -42.0),   # New Zealand
    (9, -165.0, -10.0),  # Northern Cook Islands
    (10, -74.0, 40.7),   # New York
    (11, 30.7, 36.9),    # Antalya, Turkiye
    (12, 0.0, 51.5),     # London
    (13, 86.0, 55.0),    # Kemerovo, Siberia
]


def map_band(cv):
    cv.text("bold14", MARGIN, 610, "WHERE IT HAPPENED", INK)
    cv.text_right("reg10", MARGIN + WIDTH, 614,
                  "Gulf · Shenzhen · Alaska · Crimea · Congo · USA · "
                  "Pacific · New York · Antalya · London · Siberia", FAINT)
    cols, rows = 118, 28
    x_start = MARGIN + 22
    y_start = 642
    for r in range(rows):
        lat = 75 - 4.5 * r
        for c in range(cols):
            lon = -170 + 3.05 * c
            if is_land(lon, lat):
                cv.circle(x_start + c * 8, y_start + r * 5, 2, MAPDOT)
    for num, lon, lat in PINS:
        c = round((lon + 170) / 3.05)
        r = round((75 - lat) / 4.5)
        px = x_start + c * 8
        py = y_start + r * 5
        cv.circle(px, py, 9, RED)
        label = str(num)
        lw = text_width("bold10", label)
        cv.text("bold10", px - lw // 2, py - 6, label, WHITE)


# ---------------------------------------------------------------- briefs

def briefs_and_footer(cv):
    cv.rect(MARGIN, 786, WIDTH, 2, INK)
    cv.text("bold14", MARGIN, 794, "ALSO ON WEDNESDAY 18 NOVEMBER", INK)
    cv.text_right("reg11", MARGIN + WIDTH, 797, "STORIES 14–38", FAINT)
    columns = [(0, BRIEFS[0:9]), (332, BRIEFS[9:17]), (664, BRIEFS[17:25])]
    n = 14
    for x_off, items in columns:
        x = MARGIN + x_off
        yy = 800
        for item in items:
            yy += 18
            cv.text("bold12", x, yy - 1, str(n) + ".", RED)
            cv.text("reg11", x + 24, yy, item, BODY)
            n += 1
    cv.rect(MARGIN, 984, WIDTH, 1, BORDER)
    cv.text("reg11", MARGIN, 990,
            "Every story was reported on Wednesday 18 November 2026", FAINT)
    cv.text_right("reg11", MARGIN + WIDTH, 990,
                  "Sources: Reuters · AP · BBC · AFP · Al Jazeera · UN News "
                  "· The Guardian · MetService · PANA · ONS", FAINT)


# ---------------------------------------------------------------- main

def main():
    global FONTS
    here = os.path.dirname(os.path.abspath(__file__))
    FONTS = load_fonts(os.path.join(here, "fonts.bin"))
    cv = Canvas(1024, 1024, PAPER)
    masthead_and_date(cv)
    lead_panels(cv)
    story_grid(cv)
    map_band(cv)
    briefs_and_footer(cv)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    size = write_png(cv, os.path.join(out_dir, "entry.png"))
    print("entry.png:", size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
