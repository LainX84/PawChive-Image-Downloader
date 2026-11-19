# PawChive Website Analysis

Stage 1–3 findings (site structure, authentication, original-image retrieval).
Investigated on 2026-11-08 against `https://pawchive.pw/`.
`/api/v1/app_version` returned `custom` at that time.

PawChive is a fork of the Kemono archiver. Almost everything the downloader
needs is exposed by a public JSON API, so **HTML scraping and Playwright are not
required**. HTML is used only as a fallback and for diagnostics.

---

## 1. Services and identifiers

| Concept | PawChive term | Example |
|---|---|---|
| Platform | `service` | `patreon`, `fanbox`, `discord` |
| Author | creator / `user` | numeric ID `82443765`, display `name` `Exce`, `public_id` `Exce` |
| Gallery / publication | post | ID `127090789` |
| Image | `file` (main) or entry in `attachments` | see §5 |

A creator is uniquely identified by **(service, creator_id)**. The same numeric
ID can exist on different services, so the service is always part of the key.

`public_id` is **not** accepted in URLs or the API
(`/patreon/user/Exce` → 404). Only the numeric ID works.

## 2. URL patterns (user-facing)

| Type | Pattern |
|---|---|
| Creator profile | `https://pawchive.pw/{service}/user/{creator_id}` (optional `?o=N`, `?q=...`) |
| Post (gallery) | `https://pawchive.pw/{service}/user/{creator_id}/post/{post_id}` |

A post URL always contains its creator, so "paste a gallery URL → offer to add
its author" can be done offline with a regex and confirmed with the profile
endpoint. Discord uses `/discord/server/...`. That URL shape exists, but it is
out of scope for image archiving (no titles or pages).

## 3. JSON API

Base: `https://pawchive.pw/api/v1`. All endpoints below answered **without
authentication** with `Content-Type: application/json`.

| Purpose | Endpoint | Notes |
|---|---|---|
| Creator profile | `GET /{service}/user/{id}/profile` | `{id, name, service, indexed, updated, public_id, relation_id, ever_imported}`. 404 → `{"error":"Creator not found."}` |
| Creator posts (list) | `GET /{service}/user/{id}/posts?o={offset}` | Full post objects, newest first, **50 per page**. `o` must be a multiple of 50 (otherwise HTTP 400 `offset not multiple of 50`). The last page has fewer than 50 items. |
| Creator post search | `GET /{service}/user/{id}/posts?q={text}` | Server-side title/content search |
| Single post | `GET /{service}/user/{id}/post/{post_id}` | Same object plus `next` / `prev` post IDs |
| Creator tags | `GET /{service}/user/{id}/tags` | `[{tag, post_count}]` |
| Global recent posts | `GET /posts?o=N&q=...` | Not needed for monitoring |
| Creator directory | `GET /creators` | **~15 MB** — never call it from the app |
| Not found / removed | `/posts-legacy`, `/{service}/post/{id}` | 404 on this fork; do not use |

`/api/schema` (the API docs) is restricted to logged-in users. It is not
needed.

### Post object (relevant fields)

```json
{
  "id": "127090789",
  "user": "82443765",
  "service": "patreon",
  "title": "?? Evelyn ??  ",
  "content": "<p>…HTML…</p>",
  "published": "2025-04-20T21:49:13",
  "added": "2026-06-10T21:00:00",
  "edited": "2025-04-20T21:49:13",
  "file": {"name": "Bunny.png", "path": "/1ed/fe/edfe…480a.png", "server": "https://n4.pawchive.pw"},
  "attachments": [{"name": "…", "path": "…", "server": "…"}],
  "tags": "{WIP}",
  "origin": "import",
  "preview_state": "scraped",
  "has_full": true,
  "detail_fetched": true
}
```

Observations from a sample creator (248 posts):

- `file` can be `{}`, meaning there is no main file.
- **30/248 posts had no files at all** (`file == {}` and `attachments == []`),
  for example text-only announcements. → Empty galleries are common.
- In 18/248 posts the `file` path is **also** listed in `attachments`.
  → Deduplicate by path/hash within a post.
- `file.name` is not always consistent with its `path`. In one post `file.name`
  was `Barabara1.png` while the path matched the `Barabara.png` attachment.
  → Identify files by **hash**, not by name.
- Attachments include non-images (`.7z`, `.mp4`). Seen extensions: `png gif
  jpg jpeg 7z mp4`. → **All attachments are archived** (owner decision,
  2026-11-08). Non-image files (archives, videos, PDFs, …) are often extras
  or complete versions in another format, so they go into the same work
  folder as the images. Integrity is still guaranteed by the SHA-256 path
  hash. Image signature checks apply only to image types.
- `tags` is a Postgres-style array string (`"{WIP}"`) or `null`.
- `published` is a naive ISO timestamp (no zone). Treat it as UTC.
- Titles can contain `??` where emoji were lost during import.

### Availability flags

| `has_full` | `preview_state` | `origin` | Meaning |
|---|---|---|---|
| `true` | `scraped` | `import` | Full-resolution files archived ✔ |
| `true` | `pending` | `import` | Full-resolution files archived ✔ |
| `false` | `pending` | `kemono` | **Previews only.** The API still lists `attachments`, but the original URLs return **404**. The HTML page says "Missing 4 full-res photos, 1 file, as this post has not yet been imported … Previews only". |

→ When `has_full == false`, the downloader must **not** download anything and
must **not** fall back to thumbnails. Record the post as
`awaiting_full_resolution` and recheck it on a schedule (spec §5/§6).

## 4. Pagination and change detection

- Paginated by offset, 50 per page, newest first. No infinite scroll or
  lazy-loaded API. (HTML image thumbnails are lazy-loaded via `data-src`, which
  does not matter for the API.)
- An incremental scan only needs page `o=0`, and keeps going while every post
  on the page is unknown. It stops at the first page that contains an
  already-processed post that is unchanged. A full scan is needed only on first
  add and on a user-requested "rescan".
- Change detection per post: compare `edited`, `has_full`, and the set of file
  hashes against what is stored.
- The profile's `updated` timestamp changes when the creator gets new content.
  It can be used to skip listing an unchanged creator (one cheap request).

## 5. Original vs preview images

The gallery HTML shows previews and links to originals:

```html
<a class="fileThumb" download="Bunny.png"
   href="https://n4.pawchive.pw/data/1ed/fe/edfe…480a.png?f=Bunny.png">
  <img src="https://img.pawchive.pw/thumbnail/data/ed/fe/edfe…480a.png">
</a>
```

| | URL | Content |
|---|---|---|
| **Original** | `{server}/data{path}?f={urlencoded name}` | The real file. Sample: PNG, 461,997 bytes, signature `89 50 4E 47` |
| Preview | `https://img.pawchive.pw/thumbnail/data/{h[0:2]}/{h[2:4]}/{hash}.{ext}` | **WebP** (`RIFF…`) served with a misleading `.png` name and `Content-Type: image/png`; sample 17,292 bytes |

Rules derived from this:

1. Build the original URL **from the API**: `server + "/data" + path`. Never
   reconstruct it. The first path segment has an extra leading digit
   (`/1ed/fe/…` vs the thumbnail's `/ed/fe/…`) that differs between files.
2. The `server` (`n1`…`n4.pawchive.pw`, spread roughly evenly) **must** be the
   one given by the API. The same path on another node returns 404
   `text/plain`.
3. **The file name in the path is the SHA-256 of the file.** This was verified:
   the downloaded bytes hashed to exactly the name in the path. This gives a
   free, authoritative integrity check and a global duplicate key.
4. Never accept anything from `img.pawchive.pw/thumbnail/`. A preview can also
   be recognized by a WebP signature on a non-`.webp` name, or by a hash
   mismatch.
5. `?f=` only sets the download filename. Keep `name` as the original filename.

### File server behaviour

- `Accept-Ranges` works: `Range: bytes=0-15` → **206** with 16 bytes. Resume is
  supported.
- Headers: `Cache-Control: public, max-age=31536000, immutable`,
  `Last-Modified`, correct `Content-Type` (`image/png`, `application/octet-stream`
  for archives).
- 404 is `text/plain` (`404 page…`) or `application/octet-stream`. Treat 404 on
  an original as **permanent for this attempt** and recheck it with long
  backoff, since a post may be imported later.

## 6. Authentication and cookies

- Profiles, post lists, posts, and original files are all public. **No
  account, cookies, or session are needed** for the downloader's job.
- Login exists (`/account/login`) and only gates site features (API docs,
  favorites, importer keys). `robots.txt` disallows only `/account/login` and
  `/account/register`.
- Decision: the app works without authentication by default. Cookie support
  stays an **optional, advanced setting**, stored in the OS keyring and never
  logged, for possible future gating. Never import cookies automatically from
  the user's main browser profile.
- Security note: domains in the same family (`pawchive.org`) have public
  reports of malware and account theft. The app must never send credentials
  for other services, and should only follow file URLs on `*.pawchive.pw`.

## 7. Rate limiting and anti-bot

- The site is behind Cloudflare (`cf-cache-status`). API responses carry
  `Cache-Control: s-maxage=60–600`. No rate-limit headers were observed at
  about 1 request per 0.5–0.8 s.
- **Verified 2026-11-08:** a plain non-browser client (`curl` with a custom
  User-Agent `PawChiveImageDownloader/0.1`) receives the API JSON with no
  Cloudflare challenge. If a challenge ever appears (HTML instead of JSON,
  403, `cf-mitigated` header), the app reports "access blocked" and pauses.
  It does not try to bypass it (spec §2/§8.4).
- Defaults proposed: 1 concurrent API request, ≥1.5 s between API requests,
  2 concurrent file downloads per node, honor `429` + `Retry-After`, pause the
  host on `403`/challenge pages.

## 8. Title patterns found on PawChive

These are real titles from the global post search for "page". They will be the
basis for the title-parser test fixtures:

```
A big appetite part 2 (page 2)
Super Rivals #11 page 27
Louds in the club part 4 page 41
[LIFT Update] Chapter 5, Page 2
Charisma Check | Page 72
Chapter 26, Page 16                 ← no work name: needs the author's context
Kaerwyn: Issue 23 Page 78
Play House P. 23/?
The Warchief's Challenge - Page 4
Frieren: Mage´s gift page 27
Ride Home (Finished) Page 1
The Bad Tenant Ch. 27
My Own Villainess - Chapter 59 - A Life Worth Living
BEERUS CHEELAI FULL PAGE 2 SKETCH   ← "page" is not a page number here
Regarding this page...              ← no page number
```

Implications for the parser:

- Separators vary: ` - `, ` | `, `: `, `, `, `()`, `[]`, or nothing at all.
- Page markers vary: `Page N`, `page N`, `P. N`, `p4`, `N/?`, `(page N)`.
- Group markers vary: `Part`, `Chapter`, `Ch.`, `Issue`, `#N`, `Vol.`.
- Bracketed prefixes like `[LIFT Update]` and suffixes like `(Finished)`,
  `WIP`, `SKETCH` are noise for work identity but matter for confidence.
- Titles without a work name or with ambiguous "page" wording must lower
  confidence and go to user confirmation (spec §4.2).

## 9. Fragility and maintenance notes

- The API shape is Kemono's and quite stable. Validate every response against a
  schema and raise a `SiteStructureChanged` error if required fields
  (`id, title, file, attachments, has_full`) are missing.
- `has_full` / `preview_state` are fork-specific. If they disappear, default to
  "verify by hash" and treat a WebP preview as a failure.
- HTML fallback selectors (for diagnostics only): `a.fileThumb[href]`,
  `.post__attachment-link`, `h1.post__title`, `.post__published`,
  `a.post__user-name`.
