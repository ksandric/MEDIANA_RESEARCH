from __future__ import annotations

import gzip
import hashlib
import html
import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import formatdate
from functools import lru_cache
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
HTML_DIR = STATIC_DIR / "html"
INDEX_FILE = HTML_DIR / "page.html"
DRAFTS_DIR = BASE_DIR / "drafts"
EXPLORER_FILE = HTML_DIR / "explorer.html"  # project explorer widget, filled from the newest CSV
PROJECTS_FILE = HTML_DIR / "projects.html"  # standalone page for the widget: /projects

SITE_URL = "https://mediana-research.com"
SITE_NAME = "Mediana Research"
ICON_URL = "/static/images/icon-180.png"
SHARE_IMAGE_URL = f"{SITE_URL}/static/images/icon-512.png"

MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь",
             "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS_EN = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

DOWNLOAD_SUFFIXES = {".pdf", ".csv"}
TITLE_TAG = re.compile(rb"<title>.*?</title>", re.S | re.I)
DESCRIPTION_TAG = re.compile(rb'<meta\s+name="description"[^>]*>\s*', re.I)
HTML_TAG = re.compile(rb"<html(?![^>]*\blang=)", re.I)
RESEARCH_PDF = re.compile(rf"mediana-research_({'|'.join(MONTHS_EN)})(\d{{4}})\.pdf")
DATA_CSV = re.compile(r"mediana-research_(0[1-9]|1[0-2])(\d{4})\.csv")
EXPLORER_MARK = "<!--MX:EXPLORER-->"
CSV_MARK = "<!--MX:CSV-->"
SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vR04aAelBkYuAAWPwcN1cY5gu_8yQ8EDbyBoEe1xPfObbaO0bMUUlx6DkuHLsNLUCX9azVcsImTVXxf/pubhtml"
)
PR_LINK = re.compile(r'<a href="/pr/(\d{4})/(\d{2})/(\d{2})">(.*?)</a>(?:.*?/(pr_\d+\.pdf)")?')

NOT_FOUND_PAGE = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Страница не найдена | {SITE_NAME}</title>
<meta name="robots" content="noindex">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="{ICON_URL}" type="image/png">
</head>
<body style="font-family: sans-serif; text-align: center; padding: 48px 16px; color: #332b40;">
<h1>404</h1>
<p>Такой страницы нет.</p>
<p><a href="/">На главную {SITE_NAME}</a></p>
</body>
</html>
"""

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Build "/" and "/projects" once at startup, so the first visitor gets them from the cache.
    for template in (INDEX_FILE, PROJECTS_FILE):
        rendered_page(template)
    yield


app = FastAPI(title=SITE_NAME, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static/images", StaticFiles(directory=STATIC_DIR / "images"), name="images")


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 404:
        return HTMLResponse(NOT_FOUND_PAGE, status_code=404)
    return await http_exception_handler(request, exc)


# ---------------------------------------------------------------- SEO

def seo_head(*, title: str, headline: str, description: str, path: str,
             published: Optional[str] = None, pdf: Optional[str] = None) -> bytes:
    """<head> block for a research / press-release page.

    Those pages are pdf2htmlEX exports with an empty <title>, so the tags are
    added while serving: a new month needs no manual SEO work.
    """
    url = SITE_URL + path
    article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": description,
        "inLanguage": "ru",
        "mainEntityOfPage": url,
        "image": [SHARE_IMAGE_URL],
        "author": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL + "/"},
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "logo": {"@type": "ImageObject", "url": SHARE_IMAGE_URL},
        },
    }
    if published:
        article["datePublished"] = published
    breadcrumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": SITE_NAME, "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": headline, "item": url},
        ],
    }
    e = html.escape
    lines = [
        f"<title>{e(title)}</title>",
        f'<meta name="description" content="{e(description)}"/>',
        f'<link rel="canonical" href="{url}"/>',
        '<meta property="og:type" content="article"/>',
        f'<meta property="og:site_name" content="{SITE_NAME}"/>',
        '<meta property="og:locale" content="ru_RU"/>',
        f'<meta property="og:title" content="{e(headline)}"/>',
        f'<meta property="og:description" content="{e(description)}"/>',
        f'<meta property="og:url" content="{url}"/>',
        f'<meta property="og:image" content="{SHARE_IMAGE_URL}"/>',
        '<meta name="twitter:card" content="summary"/>',
        f'<link rel="icon" href="{ICON_URL}" type="image/png" sizes="180x180"/>',
        f'<link rel="apple-touch-icon" href="{ICON_URL}"/>',
    ]
    if published:
        lines.append(f'<meta property="article:published_time" content="{published}"/>')
    if pdf:
        lines.append(f'<link rel="alternate" type="application/pdf" href="{SITE_URL}/{pdf}"/>')
    for data in (article, breadcrumbs):
        payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        lines.append(f'<script type="application/ld+json">{payload}</script>')
    return "\n".join(lines).encode()


@lru_cache(maxsize=1)
def _press_releases(index_mtime: int) -> dict[tuple[str, str, str], tuple[str, Optional[str]]]:
    text = INDEX_FILE.read_text(encoding="utf-8")
    return {
        (y, m, d): (html.unescape(title).strip(), pdf)
        for y, m, d, title, pdf in PR_LINK.findall(text)
    }


def press_releases() -> dict[tuple[str, str, str], tuple[str, Optional[str]]]:
    """Press-release titles and PDFs, taken from the list on the index page."""
    return _press_releases(INDEX_FILE.stat().st_mtime_ns)


def research_pdf(year: str, month: str) -> Optional[str]:
    name = f"mediana-research_{MONTHS_EN[int(month) - 1]}{year}.pdf"
    return name if (STATIC_DIR / name).is_file() else None


def research_draft(year: str, month: str) -> Path:
    return DRAFTS_DIR / f"mediana-research_{month}{year}.html"


def research_path(year: str, month: str) -> Optional[str]:
    """Address of a month's research page.

    From August 2026 on a month is an HTML research in drafts/ and lives at /{year}/{month};
    earlier months are pdf2htmlEX exports at /article/{year}/{month}.
    """
    if research_draft(year, month).is_file():
        return f"/{year}/{month}"
    if (HTML_DIR / f"{month}{year}.html").is_file():
        return f"/article/{year}/{month}"
    return None


def research_head(year: str, month: str) -> bytes:
    period = f"{MONTHS_RU[int(month) - 1]} {year}"
    return seo_head(
        title=f"Алготрейдинг криптовалют: исследование рынка за {period} | {SITE_NAME}",
        headline=f"Рынок алгоритмического трейдинга криптовалют: исследование за {period}",
        description=(
            f"Исследование {SITE_NAME} «Рынок алгоритмического трейдинга криптовалют» за {period}: "
            "доходность, убыточность и выживаемость алготрейдинговых проектов, индекс MEDIANA. "
            "Отчёт в PDF и данные в CSV."
        ),
        path=research_path(year, month) or f"/article/{year}/{month}",
        pdf=research_pdf(year, month),
    )


def pdf_canonical(name: str) -> Optional[str]:
    """HTML page a PDF duplicates, so search engines index the page, not the file."""
    if m := RESEARCH_PDF.fullmatch(name):
        month = f"{MONTHS_EN.index(m[1]) + 1:02d}"
        if path := research_path(m[2], month):
            return SITE_URL + path
    for (y, mo, d), (_, pdf) in press_releases().items():
        if pdf == name:
            return f"{SITE_URL}/pr/{y}/{mo}/{d}"
    return None


# ---------------------------------------------------------------- pages

def html_page(request: Request, path: Path, head: bytes) -> Response:
    if not path.is_file():
        raise HTTPException(status_code=404)
    stat = path.stat()
    etag = '"' + hashlib.md5(f"{stat.st_mtime_ns}-{stat.st_size}-".encode() + head).hexdigest() + '"'
    headers = {"ETag": etag, "Last-Modified": formatdate(stat.st_mtime, usegmt=True)}
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers=headers)

    data = path.read_bytes()
    if b'name="description"' in head:
        data = DESCRIPTION_TAG.sub(b"", data)  # the head brings its own
    data, replaced = TITLE_TAG.subn(lambda _: head, data, count=1)
    if not replaced:
        data = data.replace(b"</head>", head + b"\n</head>", 1)
    data = HTML_TAG.sub(b'<html lang="ru"', data, count=1)
    return Response(data, media_type="text/html; charset=utf-8", headers=headers)


# ---------------------------------------------------------------- project explorer

def latest_csv() -> Optional[Path]:
    """Newest monthly data file: static/mediana-research_MMYYYY.csv with the latest year and month.

    A new month needs only its CSV dropped into static/: "/" and "/projects" pick it up by themselves.
    """
    found = [
        ((int(m[2]), int(m[1])), f)
        for f in STATIC_DIR.glob("mediana-research_*.csv")
        if (m := DATA_CSV.fullmatch(f.name))
    ]
    return max(found)[1] if found else None


@dataclass(frozen=True)
class CachedPage:
    body: bytes
    gzipped: bytes
    etag: str
    modified: str


def _signature(*paths: Optional[Path]) -> tuple:
    """Changes whenever one of the files is edited or replaced: the cache key of a rendered page."""
    return tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths if p)


@lru_cache(maxsize=8)
def _render(template: Path, csv: Optional[Path], signature: tuple) -> CachedPage:
    page = template.read_text(encoding="utf-8")
    if csv:
        m = DATA_CSV.fullmatch(csv.name)
        period = f"{MONTHS_RU[int(m[1]) - 1]} {m[2]}"
        data = csv.read_text(encoding="utf-8-sig").replace("</", "<\\/")  # keep it inside <script>
        widget = (
            EXPLORER_FILE.read_text(encoding="utf-8")
            .replace("{{CSV_NAME}}", csv.name)
            .replace("{{PERIOD}}", period)
            .replace(CSV_MARK, data)
        )
    else:
        period = "последний месяц"
        widget = f'<p><a class="more" href="{SHEET_URL}">Открыть сводную таблицу в Google Таблицах →</a></p>'
    body = page.replace("{{PERIOD}}", period).replace(EXPLORER_MARK, widget).encode()
    newest = max(mtime for _, mtime, _ in signature) / 1e9
    return CachedPage(
        body=body,
        gzipped=gzip.compress(body, compresslevel=9, mtime=0),
        etag='W/"' + hashlib.md5(body).hexdigest() + '"',
        modified=formatdate(newest, usegmt=True),
    )


def rendered_page(template: Path) -> CachedPage:
    """Template with the explorer and the newest CSV inside, built once and kept in memory
    (plain and gzipped) until the template, the widget or the CSV changes."""
    csv = latest_csv()
    return _render(template, csv, _signature(template, EXPLORER_FILE, csv))


def cached_html(request: Request, template: Path) -> Response:
    page = rendered_page(template)
    headers = {
        "ETag": page.etag,
        "Last-Modified": page.modified,
        "Cache-Control": "public, max-age=300",
        "Vary": "Accept-Encoding",
    }
    if page.etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers=headers)
    body = page.body
    if "gzip" in request.headers.get("accept-encoding", ""):
        body = page.gzipped
        headers["Content-Encoding"] = "gzip"  # GZipMiddleware leaves encoded responses alone
    return Response(body, media_type="text/html; charset=utf-8", headers=headers)


# ---------------------------------------------------------------- pages (continued)

@app.api_route("/", methods=["GET", "HEAD"])
def page_index(request: Request) -> Response:
    return cached_html(request, INDEX_FILE)


@app.api_route("/projects", methods=["GET", "HEAD"])
def page_projects(request: Request) -> Response:
    return cached_html(request, PROJECTS_FILE)


@app.api_route("/article/{year}/{month}", methods=["GET", "HEAD"])
def page_article(request: Request, year: str, month: str) -> Response:
    if not re.fullmatch(r"\d{4}", year) or not re.fullmatch(r"0[1-9]|1[0-2]", month):
        raise HTTPException(status_code=404)
    if research_draft(year, month).is_file():
        # The month moved to /{year}/{month}: old links and search results follow it.
        return RedirectResponse(f"/{year}/{month}", status_code=301)
    return html_page(request, HTML_DIR / f"{month}{year}.html", research_head(year, month))


@app.api_route("/pr/{year}/{month}/{day}", methods=["GET", "HEAD"])
def page_press_release(request: Request, year: str, month: str, day: str) -> Response:
    if not re.fullmatch(r"\d{4}", year) or not re.fullmatch(r"\d{2}", month) or not re.fullmatch(r"\d{2}", day):
        raise HTTPException(status_code=404)
    date = f"{day}.{month}.{year}"
    headline, pdf = press_releases().get((year, month, day), (f"Пресс-релиз от {date}", None))
    head = seo_head(
        title=f"{headline} | {SITE_NAME}",
        headline=headline,
        description=(
            f"Пресс-релиз {SITE_NAME} от {date}: {headline}. "
            "Аналитика рынка алгоритмического трейдинга криптовалют."
        ),
        path=f"/pr/{year}/{month}/{day}",
        published=f"{year}-{month}-{day}",
        pdf=pdf,
    )
    return html_page(request, HTML_DIR / f"pr{day}{month}{year}.html", head)


@app.api_route("/{year}/{month}", methods=["GET", "HEAD"])
def page_research(request: Request, year: str, month: str) -> Response:
    """Month's research: standalone HTML built from the month's CSV (drafts/mediana-research_MMYYYY.html).

    The main address of every month from August 2026 on; /article/{year}/{month} redirects here.
    """
    if not re.fullmatch(r"\d{4}", year) or not re.fullmatch(r"0[1-9]|1[0-2]", month):
        raise HTTPException(status_code=404)
    return html_page(request, research_draft(year, month), research_head(year, month))


# ---------------------------------------------------------------- robots, sitemap, files

@app.api_route("/robots.txt", methods=["GET", "HEAD"])
def robots() -> PlainTextResponse:
    return PlainTextResponse(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")


@app.api_route("/sitemap.xml", methods=["GET", "HEAD"])
def sitemap() -> Response:
    pages = [((0, 0, 0), "/", INDEX_FILE)]
    if csv := latest_csv():
        pages.append(((0, 0, 0), "/projects", csv))
    for f in DRAFTS_DIR.glob("mediana-research_*.html"):
        if m := re.fullmatch(r"mediana-research_(0[1-9]|1[0-2])(\d{4})", f.stem):
            pages.append(((int(m[2]), int(m[1]), 0), f"/{m[2]}/{m[1]}", f))
    for f in HTML_DIR.glob("*.html"):
        if (m := re.fullmatch(r"(\d{2})(\d{4})", f.stem)) and not research_draft(m[2], m[1]).is_file():
            pages.append(((int(m[2]), int(m[1]), 0), f"/article/{m[2]}/{m[1]}", f))
        elif m := re.fullmatch(r"pr(\d{2})(\d{2})(\d{4})", f.stem):
            pages.append(((int(m[3]), int(m[2]), int(m[1])), f"/pr/{m[3]}/{m[2]}/{m[1]}", f))
    urls = []
    for _, path, f in sorted(pages, key=lambda p: (p[1] != "/", p[1].startswith("/pr/"), p[0])):
        modified = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).date().isoformat()
        urls.append(f"  <url><loc>{SITE_URL}{path}</loc><lastmod>{modified}</lastmod></url>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    return Response(xml, media_type="application/xml")


@app.api_route("/favicon.ico", methods=["GET", "HEAD"])
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "images" / "icon-180.png", media_type="image/png")


# Registered last: /mediana-research_aug2026.pdf, /mediana-research_082026.csv, /pr_1.pdf ...
@app.api_route("/{filename:path}", methods=["GET", "HEAD"])
def download(filename: str) -> FileResponse:
    path = (STATIC_DIR / filename).resolve()
    if (
        path.suffix.lower() not in DOWNLOAD_SUFFIXES
        or not path.is_relative_to(STATIC_DIR)
        or not path.is_file()
    ):
        raise HTTPException(status_code=404)
    headers = {}
    if path.suffix.lower() == ".pdf" and (canonical := pdf_canonical(path.name)):
        headers["Link"] = f'<{canonical}>; rel="canonical"'
    return FileResponse(path, headers=headers)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, access_log=False)
