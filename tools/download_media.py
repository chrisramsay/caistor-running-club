#!/usr/bin/env python3
"""Download the site's images and files into the folders next to each Markdown file.

Run from the export folder (the one containing media_manifest.json):
    python3 download_media.py

For each file it tries the live site, then the old server address, then the
Internet Archive's Wayback Machine. Files that already exist are skipped, so it
is safe to re-run. Anything that couldn't be found is listed in missing_media.txt.
Needs only Python 3, nothing to install.
"""
import json, os, sys, time, urllib.request, urllib.error
from urllib.parse import quote

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)  # repo root, one level up
UA = {"User-Agent": "Mozilla/5.0 (media export script)"}


def fetch(url, timeout=30):
    url = quote(url, safe=":/?&=%#~+@!$,;")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        ctype = r.headers.get("Content-Type", "")
    if "text/html" in ctype and not url.lower().endswith((".htm", ".html")):
        raise ValueError("got an HTML page instead of the file")
    if not data:
        raise ValueError("empty response")
    return data


def main():
    with open(os.path.join(TOOLS, "media_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    use_archive = "--no-archive" not in sys.argv
    ok = skipped = 0
    missing = []
    total = len(manifest)
    for n, (rel, urls) in enumerate(manifest.items(), 1):
        dest = os.path.join(HERE, *rel.split("/"))
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            skipped += 1
            continue
        tries = list(urls)
        if use_archive:
            tries += [f"https://web.archive.org/web/2id_/{u}" for u in urls]
        for u in tries:
            try:
                data = fetch(u)
            except Exception:
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            ok += 1
            src = "archive" if "web.archive.org" in u else "site"
            print(f"[{n}/{total}] ok ({src})  {rel}")
            break
        else:
            missing.append(f"{rel}\t{urls[0]}")
            print(f"[{n}/{total}] MISSING  {rel}")
        time.sleep(0.2)  # be gentle with the servers

    with open(os.path.join(HERE, "missing_media.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(missing) + ("\n" if missing else ""))
    print(f"\nDownloaded {ok}, already had {skipped}, missing {len(missing)} "
          f"(see missing_media.txt)")


if __name__ == "__main__":
    main()
