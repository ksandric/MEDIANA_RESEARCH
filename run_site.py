import hashlib
import html
import json
import re
from datetime import datetime, timezone
from email.utils import formatdate
from functools import lru_cache
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
HTML_DIR = STATIC_DIR / "html"
INDEX_FILE = HTML_DIR / "page.html"

SITE_URL = "https://mediana-research.com"
SITE_NAME = "Mediana Research"
ICON_URL = "/static/images/icon-180.png"
SHARE_IMAGE_URL = f"{SITE_URL}/static/images/icon-512.png"

MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь",
             "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS_EN = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

DOWNLOAD_SUFFIXES = {".pdf", ".csv"}
TITLE_TAG = re.compile(rb"<title>.*?</title>", re.S | re.I)
HTML_TAG = re.compile(rb"<html(?![^>]*\blang=)", re.I)
RESEARCH_PDF = re.compile(rf"mediana-research_({'|'.join(MONTHS_EN)})(\d{{4}})\.pdf")
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

app = FastAPI(title=SITE_NAME, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static/images", StaticFiles(directory=STATIC_DIR / "images"), name="images")


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 404:
        return HTMLResponse(NOT_FOUND_PAGE, status_code=404)
    return await http_exception_handler(request, exc)


# ---------------------------------------------------------------- SEO

def seo_head(*, title: str, headline: str, description: str, path: str,
             published: str | None = None, pdf: str | None = None) -> bytes:
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
def _press_releases(index_mtime: int) -> dict[tuple[str, str, str], tuple[str, str | None]]:
    text = INDEX_FILE.read_text(encoding="utf-8")
    return {
        (y, m, d): (html.unescape(title).strip(), pdf)
        for y, m, d, title, pdf in PR_LINK.findall(text)
    }


def press_releases() -> dict[tuple[str, str, str], tuple[str, str | None]]:
    """Press-release titles and PDFs, taken from the list on the index page."""
    return _press_releases(INDEX_FILE.stat().st_mtime_ns)


def research_pdf(year: str, month: str) -> str | None:
    name = f"mediana-research_{MONTHS_EN[int(month) - 1]}{year}.pdf"
    return name if (STATIC_DIR / name).is_file() else None


def pdf_canonical(name: str) -> str | None:
    """HTML page a PDF duplicates, so search engines index the page, not the file."""
    if m := RESEARCH_PDF.fullmatch(name):
        month = f"{MONTHS_EN.index(m[1]) + 1:02d}"
        if (HTML_DIR / f"{month}{m[2]}.html").is_file():
            return f"{SITE_URL}/article/{m[2]}/{month}"
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
    data, replaced = TITLE_TAG.subn(lambda _: head, data, count=1)
    if not replaced:
        data = data.replace(b"</head>", head + b"\n</head>", 1)
    data = HTML_TAG.sub(b'<html lang="ru"', data, count=1)
    return Response(data, media_type="text/html; charset=utf-8", headers=headers)


@app.api_route("/", methods=["GET", "HEAD"])
def page_index() -> FileResponse:
    return FileResponse(INDEX_FILE, media_type="text/html; charset=utf-8")


@app.api_route("/article/{year}/{month}", methods=["GET", "HEAD"])
def page_article(request: Request, year: str, month: str) -> Response:
    if not re.fullmatch(r"\d{4}", year) or not re.fullmatch(r"0[1-9]|1[0-2]", month):
        raise HTTPException(status_code=404)
    period = f"{MONTHS_RU[int(month) - 1]} {year}"
    head = seo_head(
        title=f"Алготрейдинг криптовалют: исследование рынка за {period} | {SITE_NAME}",
        headline=f"Рынок алгоритмического трейдинга криптовалют: исследование за {period}",
        description=(
            f"Исследование {SITE_NAME} «Рынок алгоритмического трейдинга криптовалют» за {period}: "
            "доходность, убыточность и выживаемость алготрейдинговых проектов, индекс MEDIANA. "
            "Отчёт в PDF и данные в CSV."
        ),
        path=f"/article/{year}/{month}",
        pdf=research_pdf(year, month),
    )
    return html_page(request, HTML_DIR / f"{month}{year}.html", head)


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


# ---------------------------------------------------------------- robots, sitemap, files

@app.api_route("/robots.txt", methods=["GET", "HEAD"])
def robots() -> PlainTextResponse:
    return PlainTextResponse(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")


@app.api_route("/sitemap.xml", methods=["GET", "HEAD"])
def sitemap() -> Response:
    pages = [((0, 0, 0), "/", INDEX_FILE)]
    for f in HTML_DIR.glob("*.html"):
        if m := re.fullmatch(r"(\d{2})(\d{4})", f.stem):
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
