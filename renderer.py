"""
renderer.py -  Render an EPUB's OPS pages to PDF via headless Chromium.

Usage:
    python renderer.py <path-to-OPS-folder> [output.pdf] [--pages 1-10] [--workers 4]

Requirements:
    pip install playwright pypdf
    python -m playwright install chromium

Note:
    All binaries get cached to ~/.cache/ms-playwright/
    The OPS folder is the one which typically houses all your `*.xhtml` files
"""

import argparse
import asyncio
import re
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from playwright.async_api import async_playwright
from pypdf import PdfWriter

# CLI

def parse_args():
    p = argparse.ArgumentParser(description="Render EPUB OPS pages to PDF")
    p.add_argument("ops_dir", help="Path to the OPS folder")
    p.add_argument("output", nargs="?", default="output.pdf", help="Output PDF path")
    p.add_argument(
        "--pages", default=None, help="Page range, e.g. 1-50 or 1,3,5 or 1-10,20-30"
    )
    p.add_argument("--port", type=int, default=18765, help="Local HTTP server port")
    p.add_argument(
        "--timeout",
        type=int,
        default=30000,
        help="Per-page timeout in ms (default 30000)",
    )
    p.add_argument(
        "--workers", type=int, default=4, help="Parallel browser pages (default 4)"
    )
    return p.parse_args()


def parse_page_range(spec, total):
    if not spec:
        return list(range(1, total + 1))
    indices = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            indices.update(range(int(a), int(b) + 1))
        else:
            indices.add(int(part))
    return sorted(i for i in indices if 1 <= i <= total)


# HTTP server (no chdir - serves files by absolute path)

def make_handler(ops_dir: Path):
    """Return an HTTPRequestHandler class rooted at ops_dir."""

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ops_dir), **kwargs)

        def log_message(self, *_):
            pass

    return Handler


def start_server(ops_dir: Path, port: int):
    handler = make_handler(ops_dir)
    server = HTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# Page discovery

def discover_pages(ops_dir: Path):
    files = sorted(
        f.name
        for f in ops_dir.glob("Pg*.xhtml")
        if re.match(r"Pg\d+\.xhtml", f.name, re.IGNORECASE)
    )
    if not files:
        files = sorted(
            f.name for f in ops_dir.glob("*.xhtml") if "toc" not in f.name.lower()
        )
    return files


# Async rendering

async def render_page(page, url: str, timeout: int, out_path: Path):
    await page.goto(url, wait_until="networkidle", timeout=timeout)
    await page.wait_for_timeout(300)
    await page.pdf(
        path=str(out_path),
        print_background=True,
        prefer_css_page_size=True,
    )


async def render_all(port, page_files, indices, timeout, workers, tmp_dir):
    results = {}
    total = len(indices)
    done = 0

    # Semaphore limits how many pages render concurrently
    sem = asyncio.Semaphore(workers)

    async def render_one(pg_i):
        nonlocal done
        fname = page_files[pg_i - 1]
        url = f"http://127.0.0.1:{port}/{fname}"
        out_path = tmp_dir / f"page_{pg_i:04d}.pdf"

        async with sem:
            # Each task gets its own fresh browser page to avoid any state bleed
            bpage = await context.new_page()
            try:
                await render_page(bpage, url, timeout, out_path)
                results[pg_i] = out_path
            except Exception as e:
                print(f"\n  [!!]  page {pg_i} ({fname}): {e}", flush=True)
            finally:
                await bpage.close()
                done += 1
                print(f"\r  Rendered {done}/{total} pages…", end="", flush=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport={"width": 816, "height": 1056})
        try:
            await asyncio.gather(*[render_one(i) for i in indices])
        finally:
            await context.close()
            await browser.close()

    print()
    return [results[i] for i in indices if i in results]


# Merge

def merge_pdfs(pdf_paths, output_path):
    writer = PdfWriter()
    for p in pdf_paths:
        writer.append(str(p))
    with open(output_path, "wb") as f:
        writer.write(f)


# Main

async def main_async():
    args = parse_args()
    ops_dir = Path(args.ops_dir).resolve()

    if not ops_dir.is_dir():
        sys.exit(f"Error: {ops_dir} is not a directory")

    page_files = discover_pages(ops_dir)
    if not page_files:
        sys.exit("No page XHTML files found in OPS directory")

    print(f"Found {len(page_files)} pages in {ops_dir}")

    indices = parse_page_range(args.pages, len(page_files))
    print(f"Rendering {len(indices)} page(s) with {args.workers} workers…")

    tmp_dir = Path("/tmp/epub_pdf_tmp")
    tmp_dir.mkdir(exist_ok=True)

    server = start_server(ops_dir, args.port)
    time.sleep(0.3)

    try:
        pdf_paths = await render_all(
            args.port,
            page_files,
            indices,
            args.timeout,
            args.workers,
            tmp_dir,
        )
    finally:
        server.shutdown()

    if not pdf_paths:
        sys.exit("No pages were rendered successfully.")

    print(f"Merging {len(pdf_paths)} PDFs → {args.output}")
    merge_pdfs(pdf_paths, args.output)

    size_mb = Path(args.output).stat().st_size / 1_048_576
    print(f"Done! {args.output}  ({size_mb:.1f} MB)")

    for p in tmp_dir.glob("page_*.pdf"):
        p.unlink()


if __name__ == "__main__":
    asyncio.run(main_async())
