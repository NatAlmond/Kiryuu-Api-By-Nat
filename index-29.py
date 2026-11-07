"""
Kiryuu API by Nat — v1.1.0
Scraper v7.kiryuu.to
Fix: search AJAX+nonce, pagination /manga/page/N/, chapter number parse, 404 detail
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

BASE = os.environ.get("KIRYUU_BASE", "https://v7.kiryuu.to").rstrip("/")
TIMEOUT = float(os.environ.get("KIRYUU_TIMEOUT", "30"))

app = FastAPI(title="Kiryuu API by Nat", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    "Referer": BASE + "/",
}


async def fetch(url: str, referer: str = "", method: str = "GET", data: Optional[dict] = None, extra_headers: Optional[dict] = None) -> tuple[int, str]:
    h = {**HEADERS}
    if referer:
        h["Referer"] = referer
    if extra_headers:
        h.update(extra_headers)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            if method.upper() == "POST":
                r = await client.post(url, data=data or {}, headers=h)
            else:
                r = await client.get(url, headers=h)
    except httpx.TimeoutException:
        raise HTTPException(504, "Timeout Kiryuu")
    except Exception as e:
        raise HTTPException(502, f"Fetch gagal: {type(e).__name__}")
    return r.status_code, r.text


def abs_url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(BASE + "/", href)


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        m = re.search(r"/manga/([a-z0-9\-]+)/?$", href, re.I)
        if not m:
            continue
        slug = m.group(1).lower()
        if slug in seen or slug in ("page", "manga", "genre", "status", "type", "library", "bookmark"):
            continue
        if re.match(r"^page-?\d*$", slug):
            continue
        seen.add(slug)

        img = a.find("img")
        thumb = ""
        if img:
            thumb = (img.get("src") or img.get("data-src") or img.get("data-lazy-src") or "").strip()

        title = (a.get("title") or "").strip()
        if not title and img and img.get("alt"):
            title = img.get("alt").strip()
        if not title:
            title = a.get_text(" ", strip=True)
        if (not title or title.lower() == slug) and a.parent:
            pt = a.parent.get_text(" ", strip=True)
            if pt and len(pt) > 2:
                title = pt
        if not title or len(title) < 2 or title.lower() == slug:
            title = slug.replace("-", " ").title()
        title = re.split(r"\bChapter\b", title, maxsplit=1, flags=re.I)[0].strip() or title
        if title.lower() in ("next", "prev", "previous"):
            continue

        out.append({
            "judul": title[:150],
            "slug": slug,
            "thumbnail": abs_url(thumb) if thumb else "",
            "sampul": abs_url(thumb) if thumb else "",
            "url": abs_url(href),
            "type": "MANGA",
            "source": "kiryuu",
        })
        if len(out) >= 48:
            break
    return out


def parse_chapter_href(href: str, label: str = "") -> dict:
    full = abs_url(href)
    cid = full.rstrip("/").split("/")[-1]
    # chapter-1.833534 → number=1, post_id=833534
    # chapter-12 → number=12
    # chapter-12-5 or chapter-12.5 → number=12.5
    number = ""
    post_id = ""
    m = re.search(r"chapter-(\d+)(?:\.(\d+))?$", cid, re.I)
    if m:
        left, right = m.group(1), m.group(2)
        if right and len(right) >= 5:
            # likely WP post id suffix: chapter-1.833534
            number = left
            post_id = right
        elif right:
            number = f"{left}.{right}"
        else:
            number = left
    else:
        m2 = re.search(r"(\d+(?:\.\d+)?)", label or cid)
        if m2:
            number = m2.group(1)
    judul = (label or "").strip() or (f"Chapter {number}" if number else cid)
    return {
        "judul": judul[:120],
        "title": judul[:120],
        "slug": cid,
        "number": str(number),
        "id": post_id or cid,
        "url": full,
    }


def is_not_found(status: int, html: str) -> bool:
    if status == 404:
        return True
    low = (html or "")[:4000].lower()
    markers = (
        "page not found",
        "halaman tidak ditemukan",
        "404 not found",
        "oops! that page can",
        "tidak ditemukan",
    )
    return any(m in low for m in markers)


def parse_detail(html: str, slug: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    title = slug.replace("-", " ").title()
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True) or title

    syn = ""
    for sel in (
        "[itemprop=description]",
        ".entry-content",
        ".desc",
        ".summary__content",
        ".sertoinf",
        "meta[name=description]",
    ):
        if sel.startswith("meta"):
            el = soup.select_one(sel)
            if el and el.get("content"):
                # avoid generic site description
                c = el["content"].strip()
                if c and "baca manga" not in c.lower()[:40]:
                    syn = c
                break
        else:
            el = soup.select_one(sel)
            if el:
                t = el.get_text(" ", strip=True)
                if len(t) > 40:
                    syn = t
                    break

    thumb = ""
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        thumb = og["content"].strip()
    if not thumb:
        for img in soup.find_all("img"):
            src = (img.get("src") or img.get("data-src") or "").strip()
            if "uploads" in src and not any(x in src.lower() for x in ("logo", "icon", "emoji")):
                thumb = src
                break

    genres = []
    for a in soup.select("a[href*='/genre/'], a[href*='genre='], .mgen a, a[rel=tag]"):
        g = a.get_text(strip=True)
        if g and g not in genres and len(g) < 40:
            genres.append(g)
        if len(genres) >= 15:
            break

    status = ""
    for el in soup.find_all(string=re.compile(r"Status|Ongoing|Completed|Hiatus", re.I)):
        parent = el.parent
        if parent:
            t = parent.get_text(" ", strip=True)
            m = re.search(r"(Ongoing|Completed|Hiatus)", t, re.I)
            if m:
                status = m.group(1)
                break

    chapters, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not re.search(r"/manga/.+/chapter-", href, re.I):
            continue
        full = abs_url(href)
        if full in seen:
            continue
        seen.add(full)
        chapters.append(parse_chapter_href(href, a.get_text(" ", strip=True)))

    return {
        "judul": title,
        "slug": slug,
        "thumbnail": abs_url(thumb) if thumb else "",
        "sampul": abs_url(thumb) if thumb else "",
        "sinopsis": syn[:2000],
        "genres": genres,
        "genre": genres,
        "status": status,
        "type": "MANGA",
        "total_chapter": len(chapters),
        "chapters": chapters,
        "url": f"{BASE}/manga/{slug}/",
        "source": "kiryuu",
    }


def parse_chapter_images(html: str) -> list[str]:
    images, seen = [], set()
    for u in re.findall(r'https?://cdn\.kiryuu\.io/[^"\'\s<>\\]+', (html or "").replace("\\/", "/"), re.I):
        u = u.rstrip("\\\"',);")
        if u not in seen and re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", u, re.I):
            seen.add(u)
            images.append(u)
    if len(images) < 2:
        for u in re.findall(r'https?://blogger\.googleusercontent\.com/[^"\'\s<>\\]+', html or "", re.I):
            u = u.rstrip("\\\"',);")
            if u not in seen:
                seen.add(u)
                images.append(u)
    if len(images) < 2:
        soup = BeautifulSoup(html or "", "html.parser")
        for img in soup.find_all("img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if not src.startswith("http"):
                continue
            low = src.lower()
            if any(x in low for x in ("logo", "icon", "avatar", "emoji", "banner", "gif", "themes")):
                continue
            if src not in seen:
                seen.add(src)
                images.append(src)
    return images


async def get_search_nonce() -> str:
    status, html = await fetch(BASE + "/")
    m = re.search(r"nonce=([a-f0-9]{8,})", html or "")
    if m:
        return m.group(1)
    m = re.search(r'name=["\']_ajax_nonce["\']\s+value=["\']([a-f0-9]+)["\']', html or "")
    if m:
        return m.group(1)
    return ""


async def search_ajax(q: str) -> list[dict]:
    nonce = await get_search_nonce()
    if not nonce:
        return []
    url = f"{BASE}/wp-admin/admin-ajax.php?nonce={nonce}&action=search"
    status, html = await fetch(
        url,
        referer=BASE + "/",
        method="POST",
        data={"query": q, "action": "search"},
        extra_headers={
            "HX-Request": "true",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html, */*",
        },
    )
    if status >= 400 or not html or html.strip() in ("0", "-1", ""):
        return []
    return parse_list(html)


@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Kiryuu API is running",
        "version": "1.1.0",
        "author": "Nat",
        "source": BASE,
        "endpoints": {
            "latest": "/api/latest?page=1",
            "search": "/api/search?q=judul",
            "detail": "/api/detail/{slug}",
            "chapter": "/api/chapter?url=... atau ?slug=series&chapter=chapter-1.123",
        },
    }


@app.get("/health")
async def health():
    return {"status": "online", "app": "Kiryuu-API-By-Nat", "version": "1.1.0", "base": BASE}


@app.get("/api/latest")
async def api_latest(page: int = Query(1, ge=1)):
    # FIX pagination: /manga/page/{n}/?order=update
    if page <= 1:
        url = f"{BASE}/manga/?order=update"
    else:
        url = f"{BASE}/manga/page/{page}/?order=update"
    status, html = await fetch(url)
    if status >= 400:
        raise HTTPException(status, f"Kiryuu HTTP {status}")
    data = parse_list(html)
    return {"status": True, "page": page, "total": len(data), "data": data}


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1), page: int = Query(1, ge=1)):
    q = q.strip()
    data: list[dict] = []

    # 1) Official AJAX search (correct results)
    try:
        data = await search_ajax(q)
    except HTTPException:
        data = []
    except Exception:
        data = []

    # 2) Fallback: title query (may be weak on some deploys)
    if not data:
        status, html = await fetch(f"{BASE}/manga/?title={quote(q)}&page={page}")
        if status < 400:
            data = parse_list(html)
            # if looks like unfiltered full list and query not in any slug, drop
            qparts = [p for p in re.split(r"\s+", q.lower()) if len(p) > 2]
            if data and qparts:
                related = [i for i in data if any(p in i["slug"] or p in i["judul"].lower() for p in qparts)]
                if len(related) >= 1:
                    data = related
                elif len(data) >= 20:
                    data = []  # don't return fake "search results"

    return {"status": True, "query": q, "page": page, "total": len(data), "data": data}


@app.get("/api/detail/{slug}")
async def api_detail(slug: str):
    slug = slug.strip().strip("/")
    status, html = await fetch(f"{BASE}/manga/{slug}/")
    if is_not_found(status, html):
        raise HTTPException(404, "Manga not found")
    data = parse_detail(html, slug)
    # empty shell on soft-404
    if not data.get("chapters") and not data.get("sinopsis") and not data.get("thumbnail"):
        if status >= 400:
            raise HTTPException(404, "Manga not found")
    return {"status": True, "data": data}


@app.get("/api/chapter")
async def api_chapter(
    url: str = Query(""),
    slug: str = Query(""),
    chapter: str = Query(""),
    id: str = Query(""),
):
    page_url = (url or "").strip()
    if not page_url:
        ch = (chapter or id or "").strip()
        if slug and ch:
            if ch.startswith("http"):
                page_url = ch
            elif ch.startswith("chapter-"):
                page_url = f"{BASE}/manga/{slug.strip('/')}/{ch.strip('/')}/"
            else:
                # without post id, try chapter-{n} (may 404 on Kiryuu)
                page_url = f"{BASE}/manga/{slug.strip('/')}/chapter-{ch.strip('/')}/"
        else:
            raise HTTPException(400, "Berikan url chapter penuh dari /api/detail, atau slug+chapter")
    page_url = abs_url(page_url)
    status, html = await fetch(page_url, referer=BASE + "/")
    if is_not_found(status, html):
        raise HTTPException(404, "Chapter not found")
    images = parse_chapter_images(html)
    if not images:
        raise HTTPException(404, "Gambar chapter kosong — pakai URL chapter penuh dari detail (chapter-1.ID)")
    return {
        "status": True,
        "url": page_url,
        "total": len(images),
        "images": images,
        "gambar": images,
        "source": "kiryuu",
    }


handler = Mangum(app)
