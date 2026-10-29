#!/usr/bin/env python3
"""Builds the browser assets that the server delivers:

  1. frontend/static/css/tailwind.css  the Tailwind classes your pages use
  2. frontend/static/dist/...          minified copies of custom.css and the site scripts
  3. frontend/static/dist/manifest.json  which source file each minified copy came from

The server only uses a minified copy while its source file is unchanged (the
manifest holds the source's hash). Edit main.js without rebuilding and the server
quietly serves your edited main.js instead, so a forgotten rebuild can never
ship stale code. Run this to refresh the minified copies.
Needs Node.js 18+ (https://nodejs.org).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "tailwind"
STATIC = ROOT / "frontend" / "static"
DIST = STATIC / "dist"

# Files the pages load themselves. Keep in step with ASSET_SOURCES in backend/app/main.py.
ASSETS = ("css/custom.css", "js/config.js", "js/main.js", "js/shell.js", "js/avatar-cropper.js")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run(cmd, cwd):
    print("  $", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    print("Installing build tools (Tailwind and esbuild)...")
    run(["npm", "install", "--no-audit", "--no-fund", "--silent"], TOOLS)

    print("Building Tailwind CSS...")
    run(["npx", "tailwindcss", "-c", "tailwind.config.js", "-i", "input.css", "-o", str(STATIC / "css" / "tailwind.css"), "--minify"], TOOLS)

    print("Minifying scripts and custom.css...")
    files = {}
    if DIST.exists():
        for old in DIST.rglob("*"):
            if old.is_file():
                old.unlink()
    for name in ASSETS:
        source = STATIC / name
        out_rel = f"dist/{name.rsplit('.', 1)[0]}.min.{name.rsplit('.', 1)[1]}"
        out = STATIC / out_rel
        out.parent.mkdir(parents=True, exist_ok=True)
        run(["npx", "esbuild", str(source), "--minify", "--legal-comments=none", f"--outfile={out}", "--log-level=warning"], TOOLS)
        files[name] = {"source_sha": sha(source), "dist": out_rel, "dist_sha": sha(out)}
        print(f"  {name}: {source.stat().st_size:,} -> {out.stat().st_size:,} bytes")
    (DIST / "manifest.json").write_text(json.dumps({"files": files}, indent=2) + "\n")

    print("Recording the Tailwind classes seen...")
    run([sys.executable, "tokens.py", "--write"], TOOLS)
    print("Done. Commit frontend/static/css/tailwind.css, frontend/static/dist/ and tools/tailwind/known-tokens.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
