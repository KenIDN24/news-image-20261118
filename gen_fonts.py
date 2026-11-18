#!/usr/bin/env python3
"""Build-time tool: rasterise Liberation Sans glyphs into fonts.bin.

The grading sandbox for this contest runs a stock python:3.13-slim image
(standard library only), so main.py cannot use Pillow at runtime. Instead,
this script runs once at build time on a machine that has Pillow and bakes
the glyph coverage maps main.py needs into a compact binary blob:

  fonts.bin = zlib-compressed stream of
    magic "MFNT1", u16 font count
    per font:  u8 name length, name, i16 ascent, i16 descent, u16 glyph count
    per glyph: u32 codepoint, u16 advance (1/64 px), i16 left, i16 top,
               u16 width, u16 height, u32 data length, data bytes
               (4-bit coverage, row-major, high nibble first)

main.py loads it with nothing but the standard library and blits the glyphs.
Re-run this script only if the type sizes or character set change.
"""

import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent

# (output name, ttf file, pixel size)
FONTS = [
    ("bold54", "LiberationSans-Bold.ttf", 54),     # masthead
    ("bold40", "LiberationSans-Bold.ttf", 40),     # date line
    ("bold46", "LiberationSans-Bold.ttf", 46),     # lead headline
    ("reg23", "LiberationSans-Regular.ttf", 23),   # lead deck
    ("bold27", "LiberationSans-Bold.ttf", 27),     # panel headlines
    ("reg19", "LiberationSans-Regular.ttf", 19),   # panel decks
    ("bold20", "LiberationSans-Bold.ttf", 20),     # section headers
    ("reg18", "LiberationSans-Regular.ttf", 18),   # briefs
    ("bold17", "LiberationSans-Bold.ttf", 17),     # kickers
    ("reg16", "LiberationSans-Regular.ttf", 16),   # footer
]

# Printable ASCII plus the punctuation the page actually uses.
CODEPOINTS = list(range(32, 127)) + [
    0x00A3,  # pound sign
    0x00B7,  # middle dot
    0x2013,  # en dash
    0x2014,  # em dash
    0x2018, 0x2019,  # single quotes
    0x201C, 0x201D,  # double quotes
    0x2026,  # ellipsis
]


def rasterise(font: ImageFont.FreeTypeFont, ch: str):
    """Return (advance, left, top, width, height, coverage bytes 0..255).

    The glyph is drawn once with a left-baseline anchor on a scratch image;
    left/top locate the cropped coverage box relative to the pen point and
    the baseline, so main.py can place glyphs exactly.
    """
    size = font.size
    pad = size
    baseline = size * 2
    img = Image.new("L", (size * 4, size * 4), 0)
    draw = ImageDraw.Draw(img)
    draw.text((pad, baseline), ch, font=font, fill=255, anchor="ls")
    advance = font.getlength(ch)
    bbox = img.getbbox()
    if bbox is None:  # space and other blank glyphs
        return advance, 0, 0, 0, 0, b""
    crop = img.crop(bbox)
    left = bbox[0] - pad
    top = bbox[1] - baseline
    return advance, left, top, crop.width, crop.height, crop.tobytes()


def pack_coverage(raw: bytes) -> bytes:
    """Quantise 8-bit coverage to 4-bit, two pixels per byte."""
    out = bytearray((len(raw) + 1) // 2)
    for i, value in enumerate(raw):
        nibble = value >> 4
        if i % 2 == 0:
            out[i // 2] |= nibble << 4
        else:
            out[i // 2] |= nibble
    return bytes(out)


def main() -> None:
    chunks = [b"MFNT1", struct.pack("<H", len(FONTS))]
    for name, ttf, size in FONTS:
        font = ImageFont.truetype(str(HERE / "fonts" / ttf), size)
        ascent, descent = font.getmetrics()
        glyphs = []
        for cp in CODEPOINTS:
            ch = chr(cp)
            advance, left, top, w, h, raw = rasterise(font, ch)
            data = pack_coverage(raw)
            glyphs.append(
                struct.pack(
                    "<I H h h H H I",
                    cp,
                    round(advance * 64),
                    left,
                    top,
                    w,
                    h,
                    len(data),
                )
                + data
            )
        chunks.append(struct.pack("<B", len(name)))
        chunks.append(name.encode("ascii"))
        chunks.append(struct.pack("<h h H", ascent, descent, len(glyphs)))
        chunks.extend(glyphs)
        print(f"{name}: {len(glyphs)} glyphs, ascent {ascent}, descent {descent}")
    blob = zlib.compress(b"".join(chunks), 9)
    (HERE / "fonts.bin").write_bytes(blob)
    print(f"fonts.bin: {len(blob)} bytes")


if __name__ == "__main__":
    main()
