"""Finds the Tailwind class names written in the project's source files.

Used by build_assets.py (to record what the last build saw) and by
tests/test_performance.py (to notice a class that was added after the build).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("known-tokens.txt")

SOURCES = (
    ("frontend/templates", "*.html"),
    ("frontend/static/js", "*.js"),
    ("backend/app", "*.py"),
)

VARIANTS = (
    "hover|focus|focus-visible|focus-within|active|disabled|group-hover|group-focus|peer-checked|peer-focus|dark|sm|md|lg|xl|2xl|"
    "first|last|odd|even|placeholder|file|marker|open|checked|empty|required|invalid|motion-reduce|motion-safe|print"
)
UTILITIES = (
    "bg|text|border|ring|outline|shadow|from|to|via|fill|stroke|accent|caret|divide|placeholder|decoration|"
    "p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|space|gap|w|h|min|max|size|"
    "flex|grid|col|row|order|basis|grow|shrink|items|justify|content|self|place|"
    "rounded|opacity|z|font|leading|tracking|line|whitespace|break|truncate|"
    "inset|top|left|right|bottom|translate|scale|rotate|skew|origin|transition|duration|ease|delay|animate|"
    "overflow|object|aspect|cursor|select|pointer|resize|scroll|snap|touch|"
    "blur|brightness|contrast|grayscale|backdrop|invert|sepia|saturate|hue|drop|mix|"
    "list|underline|indent|align|sr|not|columns|break-inside|hyphens"
)
_UTILITY = re.compile(
    rf"^(?:(?:{VARIANTS}):)*!?-?(?:{UTILITIES})(?:-[A-Za-z0-9\[\]/%.#:_(),'-]+)?$"
)
_STANDALONE = {
    "flex", "grid", "block", "inline", "inline-block", "inline-flex", "hidden", "relative", "absolute", "fixed",
    "sticky", "truncate", "uppercase", "lowercase", "capitalize", "underline", "italic", "border", "rounded",
    "shadow", "ring", "outline", "transition", "grow", "shrink", "sr-only", "contents", "static",
}


def collect_tokens(root: Path = ROOT) -> set[str]:
    tokens: set[str] = set()
    for folder, pattern in SOURCES:
        for path in (root / folder).rglob(pattern):
            if "vendor" in path.parts:
                continue
            for token in re.split(r"[\s\"'`<>=(){};,]+", path.read_text(errors="ignore")):
                token = token.strip()
                if 2 < len(token) < 80:
                    tokens.add(token)
    return tokens


def looks_like_utility(token: str) -> bool:
    """Shaped like a Tailwind class. Loose on purpose: it only decides which
    never-seen words are worth checking against the built stylesheet."""
    if token in _STANDALONE:
        return True
    if token.endswith((":", ".")) or "." in token.split("-")[0]:
        return False
    return "-" in token and bool(_UTILITY.match(token))


def class_names_in_css(css: str) -> set[str]:
    return {re.sub(r"\\(.)", r"\1", m.group(1)) for m in re.finditer(r"\.((?:\\.|[A-Za-z0-9_-])+)", css)}


def read_manifest() -> set[str]:
    return set(MANIFEST.read_text().split()) if MANIFEST.exists() else set()


if __name__ == "__main__":
    if "--write" in sys.argv:
        seen = sorted(t for t in collect_tokens() if looks_like_utility(t))
        MANIFEST.write_text("\n".join(seen) + "\n")
        print(f"Recorded {len(seen)} class-shaped tokens in {MANIFEST.name}")
