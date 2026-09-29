#!/usr/bin/env python3
"""Quét sitemap (kể cả sitemap index lồng nhau) và thống kê số URL mỗi sitemap con."""

import argparse
import sys
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Header giống trình duyệt thật (Chrome trên Windows) để tránh bị WAF
# (Akamai/Cloudflare-kiểu) nhận diện là bot chỉ vì User-Agent lộ liễu như
# "sitemap-checker/1.0".
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

COMMON_SITEMAP_PATHS = [
    "/sitemap_index.xml",
    "/sitemap.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
    "/sitemapindex.xml",
]


def make_session() -> requests.Session:
    """Session dùng chung để giữ cookie giữa các request (nhiều WAF set cookie
    thử thách ở request đầu rồi mới cho qua ở các request sau) và tự retry
    khi gặp lỗi mạng/rate-limit tạm thời."""
    try:
        # curl_cffi giả TLS/HTTP2 fingerprint của Chrome nên qua được Cloudflare
        # kiểu kiểm tra fingerprint mà requests bị chặn (403). Header do curl_cffi tự đặt.
        from curl_cffi import requests as cffi_requests

        return cffi_requests.Session(impersonate="chrome")
    except ImportError:
        pass

    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class BrowserResponse:
    """Response tối thiểu, tương thích với phần requests.Response mà tool dùng."""

    def __init__(self, status: int, content: bytes):
        self.status_code = status
        self.content = content
        self.ok = status < 400

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Error")


class BrowserSession:
    """Lấy nội dung bằng Chrome thật (có giao diện) qua Playwright, dùng cho
    site bật Cloudflare Managed Challenge mà requests không qua được.
    Cần: pip install playwright và Google Chrome đã cài trên máy."""

    def __init__(self, headless: bool = False):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(channel="chrome", headless=headless)
        self._page = self._browser.new_context().new_page()

    def get(self, url: str, headers: dict = None, timeout: int = 15) -> BrowserResponse:
        # Nếu gặp trang challenge của Cloudflare thì chờ nó tự giải rồi tải lại.
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        for _ in range(timeout):
            if resp is not None and resp.status < 400:
                break
            self._page.wait_for_timeout(1000)
            resp = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        body = resp.body() if resp else b""
        return BrowserResponse(resp.status if resp else 0, body)

    def close(self):
        self._browser.close()
        self._pw.stop()


def fetch_xml(session: requests.Session, url: str, timeout: int = 15, referer: str = None) -> ET.Element:
    headers = {"Referer": referer} if referer else {}
    resp = session.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def base_url_of(site_url: str) -> str:
    parsed = urlparse(site_url)
    if not parsed.scheme:
        parsed = urlparse("https://" + site_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def sitemaps_from_robots(session: requests.Session, base: str, timeout: int = 15) -> list:
    found_urls = []
    robots_url = f"{base}/robots.txt"
    try:
        resp = session.get(robots_url, timeout=timeout)
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


def sitemaps_from_common_paths(session: requests.Session, base: str, timeout: int = 15) -> list:
    for path in COMMON_SITEMAP_PATHS:
        candidate = base + path
        try:
            # Dùng GET thay vì HEAD: nhiều WAF chặn HEAD nghiêm ngặt hơn GET.
            resp = session.get(candidate, timeout=timeout)
            if resp.ok:
                return [candidate]
        except requests.RequestException:
            continue
    return []


def discover_sitemap_urls(session: requests.Session, site_url: str, timeout: int = 15) -> list:
    """Nhan vao URL trang web thuong, tu tim TAT CA URL sitemap khai bao.

    Thu tu uu tien:
    1. Doc robots.txt, gom TAT CA dong 'Sitemap: ...' (co the co nhieu dong).
    2. Neu robots.txt khong khai bao sitemap nao, thu cac duong dan pho bien
       (sitemap.xml, sitemap_index.xml, ...) va dung ngay khi thay 1 cai.
    """
    base = base_url_of(site_url)
    found_urls = sitemaps_from_robots(session, base, timeout=timeout)
    if found_urls:
        return found_urls

    found_urls = sitemaps_from_common_paths(session, base, timeout=timeout)
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


def crawl(session: requests.Session, url: str, timeout: int, results: list, visited: set,
          depth: int = 0, delay: float = 0.0, referer: str = None):
    if url in visited:
        return
    visited.add(url)

    if delay and depth > 0:
        time.sleep(delay)

    try:
        root = fetch_xml(session, url, timeout=timeout, referer=referer)
    except Exception as e:
        results.append({"sitemap": short_name(url), "url": url, "count": 0, "error": str(e)})
        return

    tag = root.tag.split("}")[-1]
    ns = root_ns(root)

    if tag == "sitemapindex":
        children = [loc.text.strip() for loc in root.findall(f"{ns}sitemap/{ns}loc") if loc.text]
        for child_url in children:
            crawl(session, child_url, timeout, results, visited, depth + 1, delay=delay, referer=url)
    elif tag == "urlset":
        urls = [loc.text.strip() for loc in root.findall(f"{ns}url/{ns}loc") if loc.text]
        results.append({"sitemap": short_name(url), "url": url, "count": len(urls), "error": None, "urls": urls})
    else:
        results.append({"sitemap": short_name(url), "url": url, "count": 0, "error": f"Unknown root tag: {tag}"})


def write_xlsx(results: list, target):
    """Ghi Excel 2 sheet: tổng hợp theo sitemap và toàn bộ URL chi tiết.
    `target` là đường dẫn file hoặc file-like (vd BytesIO)."""
    import pandas as pd

    summary = pd.DataFrame(
        [{"sitemap": r["sitemap"], "url": r["url"], "count": r["count"], "error": r["error"] or ""} for r in results]
    )
    details = pd.DataFrame(
        [{"sitemap": r["sitemap"], "loc": u} for r in results for u in r.get("urls", [])],
        columns=["sitemap", "loc"],
    )
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="sitemap_report", index=False)
        details.to_excel(writer, sheet_name="chi_tiet_url", index=False)
        for ws in writer.book.worksheets:
            _style_sheet(ws)


def _style_sheet(ws):
    """Header màu + căn giữa, đóng băng hàng đầu, bộ lọc, giãn cột theo nội dung."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.row_dimensions[1].height = 24
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="center")
            if isinstance(cell.value, int):
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right", vertical="center")

    for idx, col in enumerate(ws.columns, start=1):
        longest = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[get_column_letter(idx)].width = min(max(longest + 4, 14), 90)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


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
    parser.add_argument("--xlsx", help="Xuat Excel 2 sheet: tong hop + tat ca URL chi tiet")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        help="Thoi gian nghi (giay) giua cac request khi crawl nhieu sitemap con, "
        "de tranh bi chan vi goi qua nhanh (mac dinh 0.3s)",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Dung Chrome that (Playwright) de lay sitemap, cho site bi Cloudflare challenge chan",
    )
    parser.add_argument(
        "--no-discover",
        action="store_true",
        help="Tat tinh nang tu tim sitemap, coi url truyen vao la sitemap that",
    )
    args = parser.parse_args()

    session = BrowserSession() if args.browser else make_session()

    start_urls = [args.url]
    if not args.no_discover and not args.url.rstrip("/").lower().endswith(".xml"):
        try:
            start_urls = discover_sitemap_urls(session, args.url, timeout=args.timeout)
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
        crawl(session, start_url, args.timeout, results, visited, delay=args.delay)

    all_failed = results and all(r["error"] for r in results)
    if all_failed and not args.no_discover:
        base = base_url_of(args.url)
        fallback_urls = [u for u in sitemaps_from_common_paths(session, base, timeout=args.timeout) if u not in visited]
        if fallback_urls:
            print(
                "Cac sitemap tu robots.txt deu loi, thu tim tiep tren duong dan pho bien:"
            )
            for u in fallback_urls:
                print(f"  - {u}")
            print()
            for start_url in fallback_urls:
                crawl(session, start_url, args.timeout, results, visited, delay=args.delay)

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

    if args.xlsx:
        write_xlsx(results, args.xlsx)
        print(f"\nDa xuat Excel: {args.xlsx}")


if __name__ == "__main__":
    main()
