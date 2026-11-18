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


def icon_bridge(cv, x, y, s, bg):
    deck_y = y + int(0.60 * s)
    for tx in (x + int(0.28 * s), x + int(0.66 * s)):
        cv.rect(tx, y + int(0.16 * s), tx + int(0.07 * s),
                y + int(0.80 * s), INK)
        cv.line(tx + int(0.035 * s), y + int(0.16 * s),
                x + int(0.06 * s), deck_y, INK, t=max(2, s // 30))
        cv.line(tx + int(0.035 * s), y + int(0.16 * s),
                x + int(0.94 * s), deck_y, INK, t=max(2, s // 30))
    cv.rect(x + int(0.04 * s), deck_y, x + int(0.44 * s),
            deck_y + int(0.07 * s), INK)
    cv.rect(x + int(0.60 * s), deck_y, x + int(0.96 * s),
            deck_y + int(0.07 * s), INK)
    cv.polygon([(x + int(0.45 * s), deck_y + int(0.02 * s)),
                (x + int(0.58 * s), deck_y + int(0.02 * s)),
                (x + int(0.61 * s), y + int(0.86 * s)),
                (x + int(0.48 * s), y + int(0.86 * s))], RED)
    for i, wx in enumerate((0.14, 0.42, 0.72)):
        wy = y + int(0.90 * s) + (i % 2) * int(0.03 * s)
        cv.line(x + int(wx * s), wy, x + int((wx + 0.14) * s), wy,
                SLATE, t=max(2, s // 30))


def icon_ballot(cv, x, y, s, bg):
    cv.rect(x + int(0.35 * s), y + int(0.05 * s),
            x + int(0.65 * s), y + int(0.46 * s), bg)
    cv.frame(x + int(0.35 * s), y + int(0.05 * s),
             x + int(0.65 * s), y + int(0.46 * s), INK, t=max(2, s // 22))
    cv.line(x + int(0.42 * s), y + int(0.26 * s),
            x + int(0.48 * s), y + int(0.33 * s), GREEN, t=max(3, s // 18))
    cv.line(x + int(0.48 * s), y + int(0.33 * s),
            x + int(0.59 * s), y + int(0.16 * s), GREEN, t=max(3, s // 18))
    cv.polygon([(x + int(0.16 * s), y + int(0.48 * s)),
                (x + int(0.84 * s), y + int(0.48 * s)),
                (x + int(0.76 * s), y + int(0.93 * s)),
                (x + int(0.24 * s), y + int(0.93 * s))], INK)
    cv.rect(x + int(0.36 * s), y + int(0.56 * s),
            x + int(0.64 * s), y + int(0.62 * s), bg)


def icon_globe(cv, x, y, s, bg):
    cx, cy = x + s // 2, y + s // 2
    r = int(0.42 * s)
    cv.circle(cx, cy, r, INK)
    cv.circle(cx, cy, r - max(3, s // 20), bg)
    for frac in (-0.45, 0.0, 0.45):
        dy = int(frac * r)
        half = int((r * r - dy * dy) ** 0.5) - 2
        cv.line(cx - half, cy + dy, cx + half, cy + dy, INK,
                t=max(2, s // 30))
    cv.ellipse(cx, cy, int(0.17 * s), r - max(3, s // 20), INK)
    cv.ellipse(cx, cy, int(0.17 * s) - max(3, s // 20),
               r - 2 * max(3, s // 20), bg)


def icon_cross(cv, x, y, s, bg):
    cx, cy = x + s // 2, y + s // 2
    cv.circle(cx, cy, int(0.44 * s), RED)
    w = int(0.13 * s)
    h = int(0.27 * s)
    cv.rect(cx - w, cy - h, cx + w, cy + h, bg)
    cv.rect(cx - h, cy - w, cx + h, cy + w, bg)


def icon_virus(cv, x, y, s, bg):
    import math
    cx, cy = x + s // 2, y + s // 2
    for k in range(8):
        ang = math.pi * k / 4
        x2 = cx + int(0.40 * s * math.cos(ang))
        y2 = cy + int(0.40 * s * math.sin(ang))
        cv.line(cx, cy, x2, y2, INK, t=max(3, s // 20))
        cv.circle(x2, y2, max(3, int(0.075 * s)), INK)
    cv.circle(cx, cy, int(0.27 * s), INK)
    for dx, dy in ((-0.09, -0.05), (0.08, 0.07), (0.02, -0.13)):
        cv.circle(cx + int(dx * s), cy + int(dy * s),
                  max(2, int(0.035 * s)), bg)


def icon_chip(cv, x, y, s, bg):
    x0, y0 = x + int(0.26 * s), y + int(0.26 * s)
    x1, y1 = x + int(0.74 * s), y + int(0.74 * s)
    pin = int(0.13 * s)
    step = (y1 - y0) // 3
    for i in range(3):
        py = y0 + step // 2 + i * step
        cv.line(x0 - pin, py, x0, py, INK, t=max(3, s // 18))
        cv.line(x1, py, x1 + pin, py, INK, t=max(3, s // 18))
        px = x0 + step // 2 + i * step
        cv.line(px, y0 - pin, px, y0, INK, t=max(3, s // 18))
        cv.line(px, y1, px, y1 + pin, INK, t=max(3, s // 18))
    cv.frame(x0, y0, x1, y1, INK, t=max(3, s // 16))
    cv.rect(x + int(0.40 * s), y + int(0.40 * s),
            x + int(0.60 * s), y + int(0.60 * s), INK)


def icon_controller(cv, x, y, s, bg):
    cx, cy = x + s // 2, y + int(0.52 * s)
    cv.circle(x + int(0.16 * s), y + int(0.64 * s), int(0.15 * s), INK)
    cv.circle(x + int(0.84 * s), y + int(0.64 * s), int(0.15 * s), INK)
    cv.ellipse(cx, cy, int(0.46 * s), int(0.31 * s), INK)
    px, py = x + int(0.30 * s), cy
    cv.rect(px - int(0.10 * s), py - int(0.035 * s),
            px + int(0.10 * s), py + int(0.035 * s), bg)
    cv.rect(px - int(0.035 * s), py - int(0.10 * s),
            px + int(0.035 * s), py + int(0.10 * s), bg)
    cv.circle(x + int(0.68 * s), y + int(0.42 * s), int(0.05 * s), RED)
    cv.circle(x + int(0.79 * s), y + int(0.55 * s), int(0.05 * s), BROWN)


# ---------------------------------------------------------------- layout

MARGIN = 26
RIGHT = PAGE_W - MARGIN  # 998


def draw_panel(cv, fonts, x, y, w, h, kicker, color, headline, deck, icon):
    cv.rect(x, y, x + w, y + h, PANEL)
    cv.frame(x, y, x + w, y + h, BORDER, t=1)
    cv.rect(x, y, x + w, y + 4, color)
    cv.text(x + 16, y + 34, kicker, fonts["bold17"], color, tracking=1.0)
    icon(cv, x + w - 58, y + 10, 44, PANEL)
    head_font = fonts["bold27"]
    lines = head_font.wrap(headline, w - 32)
    base = y + 76
    for line in lines[:2]:
        cv.text(x + 16, base, line, head_font, INK)
        base += 30
    deck_font = fonts["reg19"]
    base += 2
    for line in deck_font.wrap(deck, w - 32)[:3]:
        cv.text(x + 16, base, line, deck_font, DECK)
        base += 23


def draw_lead(cv, fonts):
    x, y, w, h = MARGIN, 154, RIGHT - MARGIN, 266
    cv.rect(x, y, x + w, y + h, PANEL)
    cv.frame(x, y, x + w, y + h, BORDER, t=1)
    cv.rect(x, y, x + 8, y + h, RED)
    # Scene: a drone over the strait.
    sx0, sy0, sx1, sy1 = x + 20, y + 18, x + 280, y + h - 18
    cv.rect(sx0, sy0, sx1, sy1, SAND)
    icon_drone(cv, sx0 + 15, sy0 + 2, 230, SAND)
    cv.ellipse((sx0 + sx1) // 2, sy1 - 34, 76, 12, (208, 188, 146))
    import math
    for wy in (sy1 - 18, sy1 - 8):
        for px in range(sx0 + 10, sx1 - 10):
            yy = wy + int(2.2 * math.sin((px - sx0) / 13.0))
            cv.set(px, yy, SLATE)
            cv.set(px, yy + 1, SLATE)
    tx = x + 304
    cv.text(tx, y + 38, "MIDDLE EAST · GULF CONFLICT", fonts["bold17"], RED,
            tracking=1.5)
    head_font = fonts["bold46"]
    base = y + 90
    for line in head_font.wrap(
            "Kuwait, Bahrain say they downed Iranian drones", RIGHT - tx - 16):
        cv.text(tx, base, line, head_font, INK)
        base += 50
    deck_font = fonts["reg23"]
    base += 4
    for line in deck_font.wrap(
            "Iran's army sent combat drones at US bases in Kuwait and "
            "Bahrain after US jets struck an IRGC missile site on Iran's "
            "Qeshm Island.", RIGHT - tx - 16):
        cv.text(tx, base, line, deck_font, DECK)
        base += 31


def draw_culture(cv, fonts, x, y, w, h):
    cv.rect(x, y, x + w, y + h, PANEL)
    cv.frame(x, y, x + w, y + h, BORDER, t=1)
    cv.rect(x, y, x + w, y + 4, PLUM)
    icon_controller(cv, x + 14, y + 34, 84, PANEL)
    tx = x + 114
    cv.text(tx, y + 30, "CULTURE · GAMING", fonts["bold17"], PLUM,
            tracking=1.5)
    head_font = fonts["bold27"]
    base = y + 62
    for line in head_font.wrap("GTA VI arrives after a 13-year wait",
                               x + w - tx - 12):
        cv.text(tx, base, line, head_font, INK)
        base += 29
    cv.text(tx, y + 122, "Midnight launches start in New Zealand.",
            fonts["reg18"], DECK)


def draw_briefs(cv, fonts, x, y, w, h):
    cv.rect(x, y, x + w, y + h, PANEL)
    cv.frame(x, y, x + w, y + h, BORDER, t=1)
    cv.rect(x, y, x + w, y + 4, INK)
    cv.text(x + 16, y + 30, "ALSO TODAY", fonts["bold20"], INK, tracking=1.5)
    briefs = [
        "COP31 climate talks in Antalya split over fossil fuels",
        "UK inflation rises to 3.6%, the highest in a year",
        "Russian transport plane crashes in Siberia, killing 19",
        "Magnitude 5.3 earthquake rattles Romania overnight",
        "UN: winter cold endangers Gaza's displaced in tents",
    ]
    base = y + 58
    for brief in briefs:
        cv.rect(x + 16, base - 9, x + 22, base - 3, RED)
        cv.text(x + 30, base, brief, fonts["reg18"], DECK)
        base += 19


def build_page(fonts):
    cv = Canvas(PAGE_W, PAGE_H, PAPER)
    # Masthead
    cv.rect(MARGIN, 16, RIGHT, 20, INK)
    cv.rect(MARGIN, 24, RIGHT, 25, INK)
    cv.text_centered(PAGE_W // 2, 84, "THE DAY IN WORLD NEWS",
                     fonts["bold54"], INK, tracking=2.0)
    cv.text_centered(PAGE_W // 2, 134, "Wednesday 18 November 2026",
                     fonts["bold40"], RED)
    cv.rect(MARGIN, 148, RIGHT, 151, INK)

    draw_lead(cv, fonts)

    panels = [
        ("EUROPE · UKRAINE WAR", RED,
         "Ukraine wrecks Crimea bridge span",
         "Road deck destroyed on the Kerch Bridge. Ukraine downed 126 "
         "of 141 drones.",
         icon_bridge),
        ("AMERICAS · US POLITICS", BLUE,
         "Peltola wins Alaska; Senate 56–44",
         "AP calls the last Senate race for Democrat Mary Peltola — "
         "nine flips, the most since 1958.",
         icon_ballot),
        ("ASIA · DIPLOMACY", BROWN,
         "Xi opens APEC summit in Shenzhen",
         "Xi pledges free trade; Trump lands for Thursday's three-way "
         "summit with Xi and Putin.",
         icon_globe),
        ("AFRICA · HEALTH", GREEN,
         "Congo Ebola tops 11,000 cases",
         "WHO: cases doubled in three months, with 5,400 deaths. "
         "Children are hit hardest.",
         icon_cross),
        ("HEALTH · AMERICAS", TEAL,
         "US loses measles-free status",
         "The status held since 2000 ends after 5,400 cases and 10 "
         "deaths reported this year.",
         icon_virus),
        ("BUSINESS · TECH", PLUM,
         "Nvidia revenue doubles to $115.8bn",
         "Quarterly sales of $115.8bn beat forecasts; guidance raised "
         "to about $130bn.",
         icon_chip),
    ]
    col_x = [MARGIN, 356, 686]
    row_y = [432, 636]
    for i, (kicker, color, headline, deck, icon) in enumerate(panels):
        draw_panel(cv, fonts, col_x[i % 3], row_y[i // 3], 312, 196,
                   kicker, color, headline, deck, icon)

    draw_culture(cv, fonts, MARGIN, 842, 474, 140)
    draw_briefs(cv, fonts, 514, 842, RIGHT - 514, 140)

    # Footer
    cv.rect(MARGIN, 992, RIGHT, 993, INK)
    cv.text(MARGIN, 1014, "Every story reported on Wednesday 18 November 2026",
            fonts["reg16"], FAINT)
    cv.text_right(RIGHT, 1014, "Sources: Reuters · AP · Al Jazeera · UN News",
                  fonts["reg16"], FAINT)
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
