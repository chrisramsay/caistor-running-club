# Caistor Running Club — Markdown export

- `posts/` — 105 posts, named `YYYY-MM-DD-slug.md`. Each post's images and files go in the folder of the same name beside it.
- `pages/` — 13 pages, same arrangement.
- `_unattached/` — media from the library that no post or page used (kept in WordPress's year/month folders).
- Every file has front matter: title, dates, author, status (publish/draft/private), categories, tags, original URL, featured image, and any other media that was attached to that post.

## Getting the images

The links are already pointing at the right local files; they just need downloading:

    python3 download_media.py

It tries the live site, then the old server IP, then the Wayback Machine. Re-run it any time; it skips files it already has. Anything not found is listed in `missing_media.txt`. Add `--no-archive` to skip the Wayback Machine.
