#!/usr/bin/env python3
"""Convert a WordPress WXR export into Markdown files with per-post media folders.

Writes:
  posts/YYYY-MM-DD-slug.md   (+ posts/YYYY-MM-DD-slug/ for its media)
  pages/slug.md              (+ pages/slug/ for its media)
  _unattached/YYYY/MM/...    media in the library not tied to any post or page
  media_manifest.json        what download_media.py should fetch, and where
"""
import json, os, re, subprocess, sys, html
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, unquote

NS = {
    "wp": "http://wordpress.org/export/1.2/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "excerpt": "http://wordpress.org/export/1.2/excerpt/",
    "dc": "http://purl.org/dc/elements/1.1/",
}
SITE = "https://caistorrunningclub.com"
OLD_HOSTS = {"46.51.166.150", "caistorrunningclub.com", "www.caistorrunningclub.com"}
UPLOAD_RE = re.compile(r"""https?://([^/"'\s]+)(/wp-content/uploads/[^"'\s)<>,]+)""", re.I)

src, out = sys.argv[1], sys.argv[2]
root = ET.parse(src).getroot()
items = root.findall(".//item")
t = lambda el, tag: (el.findtext(tag, default="", namespaces=NS) or "")

authors = {a.findtext("wp:author_login", namespaces=NS): a.findtext("wp:author_display_name", namespaces=NS)
           for a in root.findall(".//wp:author", NS)}
attachments = {}
for it in items:
    if t(it, "wp:post_type") == "attachment":
        attachments[t(it, "wp:post_id")] = {
            "url": t(it, "wp:attachment_url"), "parent": t(it, "wp:post_parent"), "title": t(it, "title")}

manifest = {}          # local relative path -> list of candidate URLs
claimed_urls = set()   # upload paths that ended up in some post/page folder


def candidates(host, path):
    path = path.split("?")[0]
    urls = [SITE + path]
    if host.lower() not in ("caistorrunningclub.com",):
        urls.append(f"http://{host}{path}")
    return urls


# ---------- HTML clean-up ----------
BLOCK_TAGS = r"(?:table|thead|tfoot|caption|col|colgroup|tbody|tr|td|th|div|dl|dd|dt|ul|ol|li|pre|form|map|area|blockquote|address|math|style|p|h[1-6]|hr|fieldset|legend|section|article|aside|hgroup|header|footer|nav|figure|figcaption|details|menu|summary)"


def wpautop(text):
    """Minimal port of WordPress's wpautop for classic-editor content."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(rf"(<{BLOCK_TAGS}[\s/>])", r"\n\n\1", text)
    text = re.sub(rf"(</{BLOCK_TAGS}>)", r"\1\n\n", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    outp = []
    for p in paras:
        if re.match(rf"^</?{BLOCK_TAGS}[\s/>]", p) or re.search(rf"</{BLOCK_TAGS}>$", p):
            outp.append(p)
        else:
            outp.append("<p>" + p.replace("\n", "<br />\n") + "</p>")
    return "\n".join(outp)


def captions(text):
    def rep(m):
        inner = m.group(1)
        img = re.search(r"(<a[^>]*>\s*)?<img[^>]*>(\s*</a>)?", inner)
        cap = re.sub(r"(<a[^>]*>\s*)?<img[^>]*>(\s*</a>)?", "", inner).strip()
        return f"<figure>{img.group(0) if img else ''}<figcaption>{cap}</figcaption></figure>"
    return re.sub(r"\[caption[^\]]*\](.*?)\[/caption\]", rep, text, flags=re.S)


def clean_html(body):
    is_blocks = "<!-- wp:" in body
    body = captions(body)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)            # block markers & comments
    body = re.sub(r'<iframe[^>]*class="wp-embedded-content".*?</iframe>', "", body, flags=re.S)
    def iframe(m):
        u = html.unescape(m.group(1))
        label = "Embedded map" if "/maps/" in u else "Embedded calendar" if "calendar" in u else "Embedded content"
        return f'<p><a href="{html.escape(u)}">{label}</a></p>'
    body = re.sub(r'<iframe[^>]*\ssrc="([^"]+)"[^>]*>.*?</iframe>', iframe, body, flags=re.S)
    body = re.sub(r"<link[^>]*>", "", body)                        # stray stylesheet tags
    body = re.sub(r'<i class="fa[^"]*"></i>\s*', "", body)          # font-awesome icons
    body = re.sub(r'<ul class="wp-block-gallery[^"]*">\s*</ul>', "", body)  # empty galleries
    if not is_blocks:
        body = wpautop(body)
    body = re.sub(r"\s(srcset|sizes)=\"[^\"]*\"", "", body)        # keep a single src
    # captions as italic lines; empty alt text takes the caption
    def fig(m):
        f = m.group(0)
        cap = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", f, re.S)
        if cap:
            plain = html.unescape(re.sub(r"<[^>]+>", "", cap.group(1))).strip().replace('"', "'")
            f = re.sub(r'alt=""', f'alt="{html.escape(plain)}"', f, count=1)
            f = f.replace(cap.group(0), f"<p><em>{cap.group(1).strip()}</em></p>" if plain else "")
        return f
    body = re.sub(r"<figure.*?</figure>", fig, body, flags=re.S)
    return body


def to_markdown(h):
    r = subprocess.run(["pandoc", "-f", "html", "-t", "gfm-raw_html", "--wrap=none"],
                       input=h, capture_output=True, text=True, check=True)
    md = r.stdout
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return md


def yaml_str(s):
    return json.dumps(s, ensure_ascii=False)


# ---------- main loop ----------
os.makedirs(out, exist_ok=True)
counts = {"post": 0, "page": 0}
report = []
for it in items:
    ptype = t(it, "wp:post_type")
    if ptype not in ("post", "page"):
        continue
    pid, slug, status = t(it, "wp:post_id"), t(it, "wp:post_name"), t(it, "wp:status")
    title = html.unescape(t(it, "title")).strip() or "(untitled)"
    date = t(it, "wp:post_date")
    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or f"id-{pid}"
    slug = unquote(slug)
    base = f"{date[:10]}-{slug}" if ptype == "post" else slug
    section = "posts" if ptype == "post" else "pages"
    media_dir = f"{section}/{base}"
    used_names = {}

    def local_for(host, path):
        """Assign a file in this post's media folder for an uploads URL; return md-relative path."""
        path = path.split("?")[0]
        key = path.lower()
        if key in used_names:
            return f"{base}/{used_names[key]}"
        name = unquote(path.rsplit("/", 1)[-1])
        stem, ext = os.path.splitext(name)
        n, cand = 1, name
        while cand.lower() in {v.lower() for v in used_names.values()}:
            n += 1; cand = f"{stem}-{n}{ext}"
        used_names[key] = cand
        manifest.setdefault(f"{media_dir}/{cand}", candidates(host, path))
        claimed_urls.add(key)
        return f"{base}/{cand}"

    raw = t(it, "content:encoded")
    body = clean_html(raw)
    body = UPLOAD_RE.sub(lambda m: local_for(m.group(1), m.group(2)), body)
    md = to_markdown(body) if body.strip() else ""

    cats = [html.unescape(c.text) for c in it.findall("category") if c.get("domain") == "category"]
    tags = [html.unescape(c.text) for c in it.findall("category") if c.get("domain") == "post_tag"]
    meta = {m.findtext("wp:meta_key", namespaces=NS): m.findtext("wp:meta_value", namespaces=NS)
            for m in it.findall("wp:postmeta", NS)}

    featured = None
    thumb = attachments.get(meta.get("_thumbnail_id", ""))
    if thumb and thumb["url"]:
        m = UPLOAD_RE.search(thumb["url"])
        if m:
            featured = local_for(m.group(1), m.group(2))

    extra = []
    for aid, a in attachments.items():
        if a["parent"] == pid and a["url"]:
            m = UPLOAD_RE.search(a["url"])
            if m and m.group(2).split("?")[0].lower() not in used_names:
                extra.append(local_for(m.group(1), m.group(2)))

    fm = ["---", f"title: {yaml_str(title)}", f"date: {date}",
          f"modified: {t(it, 'wp:post_modified')}",
          f"author: {yaml_str(authors.get(t(it, 'dc:creator'), t(it, 'dc:creator')))}",
          f"type: {ptype}", f"status: {status}", f"slug: {yaml_str(slug)}",
          f"original_url: {yaml_str(t(it, 'link'))}"]
    if ptype == "page" and t(it, "wp:post_parent") not in ("", "0"):
        fm.append(f"parent_id: {t(it, 'wp:post_parent')}")
    if cats: fm.append("categories: [" + ", ".join(yaml_str(c) for c in cats) + "]")
    if tags: fm.append("tags: [" + ", ".join(yaml_str(c) for c in tags) + "]")
    if featured: fm.append(f"featured_image: {yaml_str(featured)}")
    if extra:
        fm.append("other_attached_media:")
        fm += [f"  - {yaml_str(e)}" for e in extra]
    exc = t(it, "excerpt:encoded").strip()
    if exc: fm.append(f"excerpt: {yaml_str(html.unescape(re.sub(r'<[^>]+>', '', exc)))}")
    fm.append("---")

    doc = "\n".join(fm) + f"\n\n# {title}\n\n"
    if featured:
        doc += f"![]({featured})\n\n"
    doc += md
    os.makedirs(f"{out}/{section}", exist_ok=True)
    with open(f"{out}/{section}/{base}.md", "w", encoding="utf-8") as f:
        f.write(doc)
    counts[ptype] += 1
    report.append((section, base, status, len(used_names)))

# Media in the library that no post or page used: keep year/month structure
unatt = 0
for a in attachments.values():
    m = UPLOAD_RE.search(a["url"] or "")
    if m and m.group(2).split("?")[0].lower() not in claimed_urls:
        rel = unquote(m.group(2).split("?")[0].replace("/wp-content/uploads/", "_unattached/", 1))
        manifest.setdefault(rel, candidates(m.group(1), m.group(2)))
        unatt += 1

with open(f"{out}/media_manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=1, ensure_ascii=False)

print(counts, "media files:", len(manifest), "unattached:", unatt)
print("statuses:", {s: sum(1 for r in report if r[2] == s) for s in {r[2] for r in report}})
