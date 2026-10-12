#!/usr/bin/env python3
"""Regenerate the app icon, Android adaptive-icon layers, splash mark and favicon from the website's
own logo artwork (bill_makeing_sof/public/pwa-icon.svg), so the app and the website always match.

    python3 release/generate_icons.py

Rendering uses headless Google Chrome (transparent backgrounds); no other dependencies.
"""
import re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT.parent / 'bill_makeing_sof' / 'public' / 'pwa-icon.svg'
OUT = ROOT / 'assets' / 'images'
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
BRAND = '#4f46e5'

svg = SRC.read_text()
# the logo is the <g> group of white paths; pull out its contents
paths = re.search(r'<g transform="[^"]*">(.*)</g>', svg, re.S).group(1)
# natural size of the artwork in its own units (measured from the 512 source: it spans ~1075 x 1090)
LW, LH = 1075.0, 1090.0

def logo(cx, cy, height, fill=None):
    """The logo centred on (cx, cy) with the given rendered height."""
    s = height / LH
    body = paths if fill is None else re.sub(r'fill="#[0-9a-fA-F]+"', f'fill="{fill}"', paths)
    return f'<g transform="translate({cx - LW * s / 2:.2f},{cy - LH * s / 2:.2f}) scale({s:.5f})">{body}</g>'

def render(name, size, content, background=None):
    html = f'''<!doctype html><html><head><style>html,body{{margin:0;background:transparent}}svg{{display:block}}</style></head>
<body><svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">{content}</svg></body></html>'''
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'i.html'
        f.write_text(html)
        out = OUT / name
        subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1',
                        '--default-background-color=00000000', f'--window-size={size},{size}',
                        f'--screenshot={out}', f'file://{f}'], check=True, capture_output=True)
    print('wrote', out.relative_to(ROOT))

# iOS / store icon: opaque, full-bleed square (the OS applies its own rounded mask)
render('icon.png', 1024, f'<rect width="1024" height="1024" fill="{BRAND}"/>' + logo(512, 512, 800))

# Android adaptive icon: background colour layer + foreground logo inside the ~66% safe zone + monochrome (themed icons)
render('android-icon-background.png', 512, f'<rect width="512" height="512" fill="{BRAND}"/>')
render('android-icon-foreground.png', 512, logo(256, 256, 512 * 0.50))
render('android-icon-monochrome.png', 432, logo(216, 216, 432 * 0.50, fill='#ffffff'))

# splash: the website's rounded indigo app icon on a transparent square
render('splash-icon.png', 1024, f'<rect x="112" y="112" width="800" height="800" rx="176" fill="{BRAND}"/>' + logo(512, 512, 600))

# web favicon
render('favicon.png', 48, f'<rect width="48" height="48" rx="10" fill="{BRAND}"/>' + logo(24, 24, 36))
