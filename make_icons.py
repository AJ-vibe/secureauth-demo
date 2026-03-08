"""
Generate SecureAuth PWA icons (192×192 and 512×512) using only Python stdlib.
Produces a purple rounded-square background with a white lock glyph.

Run once:  python3 make_icons.py
"""

import os, zlib, struct

def png(width, height, pixels_rgba):
    """Encode raw RGBA pixel data as a minimal PNG byte-string."""
    def chunk(tag, data):
        c = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', c)

    raw = b''
    for y in range(height):
        raw += b'\x00'                       # filter byte per row
        for x in range(width):
            raw += bytes(pixels_rgba[y][x])  # R G B A

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    # IHDR uses RGB (color type 2); rebuild with RGBA (color type 6)
    ihdr = struct.pack('>II', width, height) + bytes([8, 6, 0, 0, 0])

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', zlib.compress(raw, 9))
        + chunk(b'IEND', b'')
    )

def make_icon(size):
    BG   = (79,  70, 229, 255)   # --primary indigo
    FG   = (255, 255, 255, 255)  # white
    ZERO = (  0,   0,   0,   0)  # transparent

    s = size
    px = [[list(ZERO)] * s for _ in range(s)]

    # ── Rounded square background ─────────────────────────────────────
    r = s // 5          # corner radius ≈ 20 % of size
    cx, cy = s // 2, s // 2

    def in_rounded_rect(x, y):
        lx, rx = r, s - 1 - r
        ty, by = r, s - 1 - r
        if lx <= x <= rx and ty <= y <= by:
            return True
        corners = [(r, r), (rx, r), (r, by), (rx, by)]
        for (ccx, ccy) in corners:
            if (x - ccx) ** 2 + (y - ccy) ** 2 <= r * r:
                return True
        if x < lx or x > rx:
            return lx <= x <= rx or (
                (x < lx and ty <= y <= by) or (x > rx and ty <= y <= by)
            )
        return False

    for y in range(s):
        for x in range(s):
            # Rounded rect (crude but effective at 192/512 px)
            margin = s * 0.08
            inner  = s - margin * 2
            nx, ny = x - margin, y - margin
            rc = inner * 0.22

            in_h = margin <= x <= s - margin
            in_v = margin <= y <= s - margin
            in_body = in_h and in_v

            # corner circles
            corners_c = [
                (margin + rc, margin + rc),
                (s - margin - rc, margin + rc),
                (margin + rc, s - margin - rc),
                (s - margin - rc, s - margin - rc),
            ]
            in_corner_zone = (
                (x < margin + rc or x > s - margin - rc) and
                (y < margin + rc or y > s - margin - rc)
            )
            if in_corner_zone:
                in_body = any(
                    (x - ccx) ** 2 + (y - ccy) ** 2 <= rc * rc
                    for ccx, ccy in corners_c
                )

            if in_body:
                px[y][x] = list(BG)

    # ── Lock body (filled rectangle) ─────────────────────────────────
    lw = s * 0.38   # lock body width
    lh = s * 0.30   # lock body height
    lx = (s - lw) / 2
    ly = s * 0.50

    for y in range(s):
        for x in range(s):
            if lx <= x <= lx + lw and ly <= y <= ly + lh:
                # round the lock body corners slightly
                cr = s * 0.04
                corners_l = [
                    (lx + cr,      ly + cr),
                    (lx + lw - cr, ly + cr),
                    (lx + cr,      ly + lh - cr),
                    (lx + lw - cr, ly + lh - cr),
                ]
                in_corner_l = (
                    (x < lx + cr or x > lx + lw - cr) and
                    (y < ly + cr or y > ly + lh - cr)
                )
                if in_corner_l:
                    ok = any(
                        (x - ccx) ** 2 + (y - ccy) ** 2 <= cr * cr
                        for ccx, ccy in corners_l
                    )
                else:
                    ok = True
                if ok:
                    px[y][x] = list(FG)

    # ── Shackle (arc approximated as thick stroked circle) ───────────
    sr      = s * 0.155   # shackle outer radius
    sthick  = s * 0.065   # stroke width
    scx     = s / 2
    scy_bot = ly          # bottom of shackle aligns with top of lock body
    scy     = scy_bot - sr * 0.45

    for y in range(s):
        for x in range(s):
            dx, dy = x - scx, y - scy
            dist   = (dx * dx + dy * dy) ** 0.5
            # Only draw the top half of the shackle
            if dy <= sr * 0.55 and abs(dist - sr) <= sthick / 2:
                px[y][x] = list(FG)

    # ── Keyhole (small circle + teardrop in lock body centre) ────────
    kx   = s / 2
    ky   = ly + lh * 0.38
    kr   = s * 0.055   # keyhole circle radius
    for y in range(s):
        for x in range(s):
            dx, dy = x - kx, y - ky
            if dx * dx + dy * dy <= kr * kr:
                px[y][x] = list(BG)
            # teardrop stem below circle
            if abs(x - kx) <= kr * 0.55 and ky <= y <= ky + kr * 1.6:
                px[y][x] = list(BG)

    return png(s, s, px)


os.makedirs('icons', exist_ok=True)
for size in (192, 512):
    data = make_icon(size)
    path = f'icons/icon-{size}.png'
    with open(path, 'wb') as f:
        f.write(data)
    print(f'  ✓  {path}  ({len(data):,} bytes)')

print('Icons ready.')
