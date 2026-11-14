"""Ingestion step 1: capture the public Getnet pages the knowledge base is built from.

    python -m scripts.ingest_getnet            # writes data/corpus/raw/<page>.md, one file per URL
    python -m scripts.ingest_getnet --check    # only report which pages changed since the last capture

Each capture keeps the page's headings as `##` sections and records source_url, retrieval date and a
content hash in its front matter. The curated files in data/corpus/ are derived from these captures;
`--check` tells you when a page changed and its curated file needs review. Set INDEX_RAW_PAGES=true to
index the raw captures alongside the curated files.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from src.rag.corpus import parse_front_matter

PAGES = {
    "get-classica": "https://site.getnet.com.br/maquininha/get-classica/",
    "get-smart": "https://site.getnet.com.br/maquininha/get-smart/",
    "todas-as-maquininhas": "https://site.getnet.com.br/todas-as-maquininhas/",
    "pix": "https://site.getnet.com.br/pix/",
    "conta-digital": "https://site.getnet.com.br/conta-digital/",
    "duvidas-faq": "https://site.getnet.com.br/duvidas/",
    "antecipacao": "https://site.getnet.com.br/get-ajuda-antecipacao-de-venda/",
    "crediario": "https://site.getnet.com.br/crediario/",
    "link-de-pagamento": "https://site.getnet.com.br/link-de-pagamento/",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; knowledge-base-ingest)", "Accept-Language": "pt-BR,pt;q=0.9"}


def html_to_sections(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"]):
        tag.decompose()
    root = soup.find("main") or soup.body or soup
    lines: list[str] = []
    for node in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th"]):
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        if len(text) < 3:
            continue
        if node.name in ("h1", "h2", "h3", "h4"):
            lines.append(f"\n## {text}")
        elif not lines or lines[-1] != text:
            lines.append(text)
    return title, "\n".join(lines).strip()


def capture(slug: str, url: str, out_dir: Path, check_only: bool, client: httpx.Client) -> str:
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"FAILED   {slug}: {type(exc).__name__}"
    title, body = html_to_sections(response.text)
    if len(body) < 200:
        return f"EMPTY    {slug}: {len(body)} characters of text (page is probably rendered client-side)"
    digest = hashlib.sha256(body.encode()).hexdigest()[:16]
    target = out_dir / f"{slug}.md"
    previous = parse_front_matter(target.read_text(encoding="utf-8"))[0].get("content_hash") if target.exists() else None
    state = "UNCHANGED" if previous == digest else ("CHANGED  " if previous else "NEW      ")
    if not check_only and previous != digest:
        target.write_text(
            f"---\nid: raw-{slug}\ntitle: {title or slug}\nsource_url: {url}\norigin: getnet_site_raw\n"
            f"retrieved_at: {date.today().isoformat()}\ncontent_hash: {digest}\n---\n{body}\n",
            encoding="utf-8",
        )
    return f"{state} {slug}: {len(body)} characters"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("data/corpus/raw"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        results = [capture(slug, url, args.out, args.check, client) for slug, url in PAGES.items()]
    print("\n".join(results))
    return 1 if any(r.startswith(("FAILED", "EMPTY")) for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
