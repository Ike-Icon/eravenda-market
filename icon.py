import cairosvg
from PIL import Image
import io

svg_code = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <defs>
    <linearGradient id="fav-green" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0F766E"/>
      <stop offset="100%" stop-color="#0A5C36"/>
    </linearGradient>
    <linearGradient id="fav-gold" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#F59E0B"/>
      <stop offset="100%" stop-color="#D97706"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="16" fill="url(#fav-green)"/>
  <path d="M24 21 C24 14, 40 14, 40 21" stroke="url(#fav-gold)" stroke-width="4.5" stroke-linecap="round" fill="none"/>
  <path d="M21 29 H43 M21 37 H36 M21 45 H43" stroke="#FFFFFF" stroke-width="4.5" stroke-linecap="round"/>
</svg>"""

# Render SVG to PNG bytes
png_data = cairosvg.svg2png(bytestring=svg_code.encode("utf-8"), output_width=64, output_height=64)

# Convert PNG bytes to ICO and save
img = Image.open(io.BytesIO(png_data))
img.save("frontend/static/favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])