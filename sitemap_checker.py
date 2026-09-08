#!/usr/bin/env python3
"""Quét sitemap (kể cả sitemap index lồng nhau) và thống kê số URL mỗi sitemap con."""

import argparse
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (sitemap-checker/1.0)"}

COMMON_SITEMAP_PATHS = [
    "/sitemap_index.xml",
    "/sitemap.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
    "/sitemapindex.xml",
]


def fetch_xml(url: str, timeout: int = 15) -> ET.Element:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def base_url_of(site_url: str) -> str:
    parsed = urlparse(site_url)
    if not parsed.scheme:
        parsed = urlparse("https://" + site_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def sitemaps_from_robots(base: str, timeout: int = 15) -> list:
    found_urls = []
    robots_url = f"{base}/robots.txt"
    try:
        resp = requests.get(robots_url, headers=HEADERS, timeout=timeout)
        if resp.ok:
            for line in resp.text.splitlines():
                line = line.strip()
                if line.lower().startswith("sitemap:"):
                    found = line.split(":", 1)[1].strip()
                    if found and found not in found_urls:
                        found_urls.append(found)
    except requests.RequestException:
        pass
    return found_urls


def sitemaps_from_common_paths(base: str, timeout: int = 15) -> list:
    for path in COMMON_SITEMAP_PATHS:
        candidate = base + path
        try:
            resp = requests.head(candidate, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if resp.status_code == 405 or resp.status_code >= 400:
                resp = requests.get(candidate, headers=HEADERS, timeout=timeout)
            if resp.ok:
                return [candidate]
        except requests.RequestException:
            continue
    return []


def discover_sitemap_urls(site_url: str, timeout: int = 15) -> list:
    """Nhan vao URL trang web thuong, tu tim TAT CA URL sitemap khai bao.

    Thu tu uu tien:
    1. Doc robots.txt, gom TAT CA dong 'Sitemap: ...' (co the co nhieu dong).
    2. Neu robots.txt khong khai bao sitemap nao, thu cac duong dan pho bien
       (sitemap.xml, sitemap_index.xml, ...) va dung ngay khi thay 1 cai.
    """
    base = base_url_of(site_url)
    found_urls = sitemaps_from_robots(base, timeout=timeout)
    if found_urls:
        return found_urls

    found_urls = sitemaps_from_common_paths(base, timeout=timeout)
    if found_urls:
        return found_urls

    raise RuntimeError(
        f"Khong tim thay sitemap nao qua robots.txt hoac cac duong dan pho bien tai {base}"
    )


def short_name(url: str) -> str:
    path = urlparse(url).path
    return path.rsplit("/", 1)[-1] or url


def root_ns(root: ET.Element) -> str:
    """Lay namespace URI cua the goc, vd '{https://.../sitemap/0.9}'."""
    if root.tag.startswith("{"):
        return root.tag.split("}")[0] + "}"
    return ""


def crawl(url: str, timeout: int, results: list, visited: set, depth: int = 0):
    if url in visited:
        return
    visited.add(url)

    try:
        root = fetch_xml(url, timeout=timeout)
    except Exception as e:
        results.append({"sitemap": short_name(url), "url": url, "count": 0, "error": str(e)})
        return

    tag = root.tag.split("}")[-1]
    ns = root_ns(root)

    if tag == "sitemapindex":
        children = [loc.text.strip() for loc in root.findall(f"{ns}sitemap/{ns}loc") if loc.text]
        for child_url in children:
            crawl(child_url, timeout, results, visited, depth + 1)
    elif tag == "urlset":
        urls = root.findall(f"{ns}url/{ns}loc")
        results.append({"sitemap": short_name(url), "url": url, "count": len(urls), "error": None})
    else:
        results.append({"sitemap": short_name(url), "url": url, "count": 0, "error": f"Unknown root tag: {tag}"})


def print_report(results: list):
    total = sum(r["count"] for r in results)
    name_w = max([len(r["sitemap"]) for r in results] + [len("Sitemap")]) + 2
    count_w = max([len(str(r["count"])) for r in results] + [len("So luong URL")]) + 2

    print(f"{'Sitemap'.ljust(name_w)}{'So luong URL'.rjust(count_w)}")
    print("-" * (name_w + count_w))
    for r in results:
        note = f"  [ERROR: {r['error']}]" if r["error"] else ""
        print(f"{r['sitemap'].ljust(name_w)}{str(r['count']).rjust(count_w)}{note}")
    print("-" * (name_w + count_w))
    print(f"{'Tong'.ljust(name_w)}{str(total).rjust(count_w)}")

    attachments = [r for r in results if "attachment" in r["sitemap"].lower()]
    if attachments:
        att_count = sum(r["count"] for r in attachments)
        if total:
            pct = att_count / total * 100
            print(f"\nLuu y: attachment-sitemap chiem {att_count}/{total} URL (~{pct:.0f}%).")


def main():
    parser = argparse.ArgumentParser(description="Kiem tra va thong ke sitemap")
    parser.add_argument(
        "url",
        help="URL sitemap (vd: .../sitemap_index.xml) hoac URL trang web thuong (vd: https://example.com) "
        "de tool tu tim sitemap",
    )
    parser.add_argument("--timeout", type=int, default=15, help="Timeout request (giay)")
    parser.add_argument("--csv", help="Xuat ket qua ra file CSV")
    parser.add_argument(
        "--no-discover",
        action="store_true",
        help="Tat tinh nang tu tim sitemap, coi url truyen vao la sitemap that",
    )
    args = parser.parse_args()

    start_urls = [args.url]
    if not args.no_discover and not args.url.rstrip("/").lower().endswith(".xml"):
        try:
            start_urls = discover_sitemap_urls(args.url, timeout=args.timeout)
            label = "sitemap" if len(start_urls) == 1 else f"{len(start_urls)} sitemap"
            print(f"Da tu tim thay {label}:")
            for u in start_urls:
                print(f"  - {u}")
            print()
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    results = []
    visited = set()
    for start_url in start_urls:
        crawl(start_url, args.timeout, results, visited)

    all_failed = results and all(r["error"] for r in results)
    if all_failed and not args.no_discover:
        base = base_url_of(args.url)
        fallback_urls = [u for u in sitemaps_from_common_paths(base, timeout=args.timeout) if u not in visited]
        if fallback_urls:
            print(
                "Cac sitemap tu robots.txt deu loi, thu tim tiep tren duong dan pho bien:"
            )
            for u in fallback_urls:
                print(f"  - {u}")
            print()
            for start_url in fallback_urls:
                crawl(start_url, args.timeout, results, visited)

    if not results:
        print("Khong tim thay sitemap nao.", file=sys.stderr)
        sys.exit(1)

    print_report(results)

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["sitemap", "url", "count", "error"])
            for r in results:
                writer.writerow([r["sitemap"], r["url"], r["count"], r["error"] or ""])
        print(f"\nDa xuat CSV: {args.csv}")


if __name__ == "__main__":
    main()
