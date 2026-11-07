# Kiryuu API by Nat

API scraper **Kiryuu** (`v7.kiryuu.to`) — v1.1.0

**By: Nat**

## Fix di v1.1.0
- Search via AJAX + nonce (bukan `?title=` palsu)
- Pagination `/manga/page/{n}/?order=update`
- Nomor chapter: `chapter-1.833534` → number `1`, id `833534`
- Detail/chapter 404 yang benar
- Response detail rapi di `data`

## Endpoint
| Path | Keterangan |
|------|------------|
| `/api/latest?page=1` | Update |
| `/api/search?q=solo` | Cari |
| `/api/detail/{slug}` | Detail + chapter |
| `/api/chapter?url=...` | Gambar (URL penuh dari detail) |

## Deploy
Upload ke root repo → Vercel Import → Deploy.

Env opsional: `KIRYUU_BASE`, `KIRYUU_TIMEOUT`
