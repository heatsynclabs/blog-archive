#!/usr/bin/env python3
"""
Build the HeatSync Labs blog archive site from the original WordPress dump.

Reads   : heatsynclabs-wp.sql  (mysqldump) + the www.heatsynclabs.org/ tree beside it
Writes  : posts/*.md            GitHub-readable Markdown, images at ../images/
          data/html/*.html      pre-rendered post bodies, images at images/
          data/posts.json       index consumed by the site
          images/**             copies of every referenced original
          thumbs/**             640px-wide JPEGs for grid views (needs `sips`)

Everything is derived. Delete posts/ data/ images/ thumbs/ and re-run.

Usage:
  python3 build/build.py --source /path/to/wordpress-export
  python3 build/build.py --source ... --skip-images     # text only, fast
"""
import argparse, html, json, os, re, shutil, sqlite3, subprocess, sys, collections, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE = os.environ.get("WP_SOURCE", "")   # or pass --source

# ---------------------------------------------------------------- dump -> sqlite
def load_sql(sql_path, db_path):
    """Parse the mysqldump into SQLite. awk/grep choke on the giant one-line INSERTs."""
    if os.path.exists(db_path):
        os.remove(db_path)
    data = open(sql_path, encoding="utf8", errors="replace").read()
    cols = {}
    for m in re.finditer(r"CREATE TABLE `(\w+)` \((.*?)\n\) ENGINE", data, re.S):
        cols[m.group(1)] = [c.group(1) for c in
                            (re.match(r"`(\w+)`", l.strip()) for l in m.group(2).split("\n")) if c]

    def rows(payload):
        i, n = 0, len(payload)
        while i < n:
            if payload[i] != "(":
                i += 1
                continue
            i += 1
            vals, cur, inq = [], "", False
            while i < n:
                ch = payload[i]
                if inq:
                    if ch == "\\":
                        cur += {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(payload[i + 1], payload[i + 1])
                        i += 2
                        continue
                    if ch == "'":
                        if i + 1 < n and payload[i + 1] == "'":
                            cur += "'"
                            i += 2
                            continue
                        inq = False
                        i += 1
                        continue
                    cur += ch
                    i += 1
                    continue
                if ch == "'":
                    inq = True
                    i += 1
                    continue
                if ch == ",":
                    vals.append(cur.strip())
                    cur = ""
                    i += 1
                    continue
                if ch == ")":
                    vals.append(cur.strip())
                    i += 1
                    break
                cur += ch
                i += 1
            yield [None if v == "NULL" else v for v in vals]
            while i < n and payload[i] in ", \n":
                i += 1

    want = {"wp_posts", "wp_users", "wp_postmeta", "wp_ngg_gallery", "wp_ngg_pictures",
            "wp_comments"}
    con = sqlite3.connect(db_path)
    made = set()
    for m in re.finditer(r"INSERT INTO `(\w+)` VALUES (.*?);\n", data, re.S):
        t = m.group(1)
        if t not in want or t not in cols:
            continue
        c = cols[t]
        if t not in made:
            con.execute(f"CREATE TABLE {t} ({','.join(chr(34)+x+chr(34) for x in c)})")
            made.add(t)
        batch = []
        for r in rows(m.group(2)):
            if len(r) != len(c):
                r = (r + [None] * len(c))[:len(c)]
            batch.append(r)
        con.executemany(f"INSERT INTO {t} VALUES ({','.join('?' * len(c))})", batch)
    con.commit()
    return con


# ---------------------------------------------------------------- helpers
def slugify(title, post_name):
    if post_name and re.match(r"^[a-z0-9\-]+$", post_name):
        return post_name[:70]
    s = re.sub(r"[^a-z0-9]+", "-", (title or "untitled").lower()).strip("-")
    return s[:70] or "untitled"


class Builder:
    def __init__(self, source, skip_images):
        self.www = os.path.join(source, "www.heatsynclabs.org")
        self.sql = os.path.join(source, "heatsynclabs-wp.sql")
        self.skip_images = skip_images
        self.con = load_sql(self.sql, os.path.join(ROOT, "build", "wp.sqlite"))
        c = self.con
        self.attached = {r[0]: r[1] for r in c.execute(
            "SELECT post_id,meta_value FROM wp_postmeta WHERE meta_key='_wp_attached_file'")}
        self.alt = {r[0]: r[1] for r in c.execute(
            "SELECT post_id,meta_value FROM wp_postmeta WHERE meta_key='_wp_attachment_image_alt'")}
        self.att_title = {r[0]: r[1] for r in c.execute(
            "SELECT ID,post_title FROM wp_posts WHERE post_type='attachment'")}
        self.att_parent = collections.defaultdict(list)
        for pid, parent in c.execute(
                "SELECT ID,post_parent FROM wp_posts WHERE post_type='attachment' ORDER BY post_date"):
            if parent and str(parent) != "0":
                self.att_parent[str(parent)].append(str(pid))
        self.gal = {str(r[0]): {"path": r[1], "title": r[2]}
                    for r in c.execute("SELECT gid,path,title FROM wp_ngg_gallery")}
        self.pics = collections.defaultdict(list)
        self.pic_by_id = {}
        for pid, gid, fn, desc, at in c.execute(
                "SELECT pid,galleryid,filename,description,alttext FROM wp_ngg_pictures "
                "ORDER BY CAST(sortorder AS INT),CAST(pid AS INT)"):
            rec = {"pid": str(pid), "gid": str(gid), "filename": fn,
                   "cap": (desc or at or "").strip()}
            self.pics[str(gid)].append(rec)
            self.pic_by_id[str(pid)] = rec
        self.users = {r[0]: r[1] for r in c.execute("SELECT ID,display_name FROM wp_users")}
        # Curated authorship corrections. wp_posts.post_author is wrong for a block of
        # 2009 posts that a "delete user and reassign" operation moved onto another
        # account; build/attribution.json documents which, and why.
        self.attrib, self.attrib_author = {}, {}
        _ap = os.path.join(ROOT, "build", "attribution.json")
        if os.path.exists(_ap):
            _a = json.load(open(_ap))
            self.attrib = _a.get("posts", {})
            self.attrib_author = _a.get("author", {})
        self.copied = {}          # wp-content/... -> images/...
        self.stats = collections.Counter()

    # -- image resolution ---------------------------------------------------
    def exists(self, rel):
        return bool(rel) and os.path.isfile(os.path.join(self.www, rel))

    def resolve(self, url):
        """A URL or path from the post body -> a path under www/, or None."""
        if not url:
            return None
        url = url.split("?")[0]
        m = re.search(r"(wp-content/(?:uploads|gallery)/[^\"'\s)]+)", url)
        if not m:
            return None
        p = m.group(1)
        if self.exists(p):
            return p
        p2 = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", p)      # strip WP size suffix
        return p2 if p2 != p and self.exists(p2) else None

    def adopt(self, rel):
        """Copy an original into images/ (flattened sensibly) and make a thumb."""
        if rel in self.copied:
            return self.copied[rel]
        parts = rel.split("/")
        if parts[1] == "uploads":
            dest = "images/uploads/" + "/".join(parts[2:])
        else:
            dest = "images/gallery/" + "/".join(parts[2:])
        src = os.path.join(self.www, rel)
        dst = os.path.join(ROOT, dest)
        if not self.skip_images:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            self.make_thumb(dest)
        self.copied[rel] = dest
        self.stats["images"] += 1
        return dest

    def make_thumb(self, dest):
        if re.search(r"\.(pdf|zip|docx?)$", dest, re.I):
            return
        tp = os.path.join(ROOT, "thumbs", dest[len("images/"):])
        tp = os.path.splitext(tp)[0] + ".jpg"
        if os.path.exists(tp):
            return
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        try:
            subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "640",
                            os.path.join(ROOT, dest), "--out", tp],
                           check=True, capture_output=True, timeout=60)
            self.stats["thumbs"] += 1
        except Exception:
            self.stats["thumb_failed"] += 1

    def thumb_of(self, dest):
        if re.search(r"\.(pdf|zip|docx?)$", dest, re.I):
            return None
        t = "thumbs/" + os.path.splitext(dest[len("images/"):])[0] + ".jpg"
        return t if os.path.exists(os.path.join(ROOT, t)) else dest

    # -- body conversion ----------------------------------------------------
    def expand(self, body, prefix):
        """Resolve shortcodes + <img> into real paths. prefix is '' or '../'.
        Returns (html_body, ordered list of image dicts)."""
        imgs = []

        def add(rel, cap):
            dest = self.adopt(rel)
            imgs.append({"src": prefix + dest, "cap": cap, "raw": dest})
            return imgs[-1]

        def singlepic(m):
            rec = self.pic_by_id.get(m.group(1))
            if not rec:
                return ""
            g = self.gal.get(rec["gid"])
            p = f"{g['path']}/{rec['filename']}" if g else None
            if not self.exists(p):
                self.stats["img_missing"] += 1
                return ""
            i = add(p, rec["cap"])
            return f'<figure><img src="{i["src"]}" alt="{html.escape(i["cap"])}">' \
                   + (f'<figcaption>{html.escape(i["cap"])}</figcaption>' if i["cap"] else "") + "</figure>"
        body = re.sub(r"\[singlepic id=(\d+)[^\]]*\]", singlepic, body)

        def gallery(m):
            gid = m.group(1)
            g, lst = self.gal.get(gid), self.pics.get(gid, [])
            if not g or not lst:
                return '<p class="note">(gallery not recovered)</p>'
            out = [f'<div class="gallery" data-count="{len(lst)}">',
                   f'<h3 class="gallery-h">Gallery — {html.escape(g["title"] or "")}</h3>']
            for rec in lst:
                p = f"{g['path']}/{rec['filename']}"
                if not self.exists(p):
                    self.stats["img_missing"] += 1
                    continue
                i = add(p, rec["cap"])
                out.append(f'<figure><a href="{i["src"]}" target="_blank" rel="noopener">'
                           f'<img loading="lazy" src="{i["src"]}" alt="{html.escape(i["cap"])}"></a>'
                           + (f'<figcaption>{html.escape(i["cap"])}</figcaption>' if i["cap"] else "")
                           + "</figure>")
            out.append("</div>")
            return "\n".join(out)
        body = re.sub(r"\[nggallery id=(\d+)[^\]]*\]", gallery, body)

        def caption(m):
            inner, attrs = m.group(2), m.group(1) or ""
            cm = re.search(r'caption="([^"]*)"', attrs)
            cap = cm.group(1) if cm else ""
            return f'<figure>{inner}' + (f'<figcaption>{cap}</figcaption>' if cap else "") + "</figure>"
        body = re.sub(r"\[caption([^\]]*)\](.*?)\[/caption\]", caption, body, flags=re.S)

        def imgtag(m):
            tag = m.group(0)
            src = re.search(r'src=["\']([^"\']+)', tag)
            raw = src.group(1) if src else ""
            # Already rewritten by singlepic()/gallery() above - leave alone.
            if re.match(r"(\.\./)?(images|thumbs)/", raw):
                return tag
            a = re.search(r'alt=["\']([^"\']*)', tag) or re.search(r'title=["\']([^"\']*)', tag)
            rel = self.resolve(raw)
            if not rel:
                # Hotlinked from somewhere else when the post was written
                # (Flickr, PayPal buttons, guestlistapp badges). Never on the
                # lab's server, so never in the dump. Link out to the original;
                # most of the Flickr ones still resolve.
                self.stats["img_external"] += 1
                host = re.match(r"https?://([^/]+)", raw)
                hn = html.escape(host.group(1)) if host else "another site"
                # Emit a <span> carrying the url. Most of these <img> tags are
                # already wrapped in a link to the Flickr photo page, and nesting
                # anchors is invalid HTML and mangles the Markdown. link_bare()
                # below turns the ones that are NOT already inside a link into
                # anchors, so every offsite image ends up clickable either way.
                if not raw.startswith("http"):
                    return f'<span class="offsite">Image missing: {html.escape(raw[:80])}</span>'
                if re.search(r"paypalobjects\.com.*pixel\.gif", raw):
                    return '<span class="offsite">PayPal tracking pixel</span>'
                return (f'<span class="offsite" data-src="{html.escape(raw)}">'
                        f'Offsite image &mdash; hosted on {hn}</span>')
            i = add(rel, (a.group(1) if a else "").strip())
            return f'<img loading="lazy" src="{i["src"]}" alt="{html.escape(i["cap"])}">'
        body = re.sub(r"<img[^>]*/?>", imgtag, body, flags=re.I)

        # Dead 2010-era Flash players (Vimeo/Flickr/YouTube .swf). The posts
        # almost always carry a plain <a> link to the same video right after,
        # so drop the player rather than leave a broken grey box.
        def deflash(m):
            """2010-era .swf players. Two kinds, and they are not the same loss:
            Vimeo = a video; Flickr slideshow = a PHOTO SET that lived on Flickr,
            never on the lab's server. Either way, link to the real thing."""
            blk = m.group(0).replace("&amp;", "&")

            if "flickr.com/apps/slideshow" in blk:
                sid = re.search(r"set_id=(\d+)", blk)
                usr = re.search(r"/photos/([^/]+)/sets/", urllib.parse.unquote(blk))
                if sid and usr:
                    url = f"https://www.flickr.com/photos/{usr.group(1)}/sets/{sid.group(1)}/"
                    self.stats["flickr_set"] += 1
                    return ('<p class="offsite-block"><strong>Flickr slideshow</strong> '
                            'This post showed a photo set hosted on Flickr, not on the lab&rsquo;s '
                            'server, so the images are not in this archive. '
                            f'<a href="{url}" target="_blank" rel="noopener">Open the set on Flickr &rarr;</a></p>')
                self.stats["flickr_set"] += 1
                return ('<p class="offsite-block"><strong>Flickr slideshow</strong> A photo set '
                        'hosted on Flickr; the set id did not survive in the dump.</p>')

            cid = re.search(r"clip_id=(\d+)", blk)
            if cid:
                self.stats["vimeo"] += 1
                return ('<p class="offsite-block"><strong>Video</strong> '
                        f'<a href="https://vimeo.com/{cid.group(1)}" target="_blank" rel="noopener">'
                        f'watch on Vimeo &rarr;</a></p>')
            yt = re.search(r"youtube\.com/v/([\w-]+)", blk)
            if yt:
                self.stats["youtube"] += 1
                return ('<p class="offsite-block"><strong>Video</strong> '
                        f'<a href="https://www.youtube.com/watch?v={yt.group(1)}" target="_blank" '
                        'rel="noopener">watch on YouTube &rarr;</a></p>')
            self.stats["flash_other"] += 1
            return '<p class="offsite-block"><strong>Flash embed</strong> The player no longer runs in any browser.</p>'
        body = re.sub(r"<object\b.*?</object>", deflash, body, flags=re.S | re.I)
        body = re.sub(r"<embed\b[^>]*>(?:</embed>)?", "", body, flags=re.I)
        body = re.sub(r"<param\b[^>]*>", "", body, flags=re.I)
        body = re.sub(r"<iframe\b[^>]*src=[\"']([^\"']*moogaloop[^\"']*)[\"'][^>]*>\s*</iframe>", "", body, flags=re.I)

        body = body.replace("<!--more-->", "")
        body = re.sub(r"\[/?(?:wp_cart|pdf)[^\]]*\]", "", body)
        body = self.link_bare(body)
        return body, imgs

    def link_bare(self, body):
        """Offsite-image notes that are NOT already inside an <a> become links.
        Ones that are keep the surrounding link and just shed the data attr, so
        we never nest anchors."""
        out, pos, depth = [], 0, 0
        for m in re.finditer(r'<a\b|</a>|<span class="offsite" data-src="([^"]*)">(.*?)</span>',
                             body, re.S | re.I):
            tok = m.group(0)
            out.append(body[pos:m.start()])
            pos = m.end()
            if tok.lower().startswith("<a"):
                depth += 1
                out.append(tok)
            elif tok.lower().startswith("</a"):
                depth = max(0, depth - 1)
                out.append(tok)
            elif depth > 0:                       # already inside a link
                out.append(f'<span class="offsite">{m.group(2)}</span>')
            else:                                  # bare - make it clickable
                self.stats["offsite_linked"] += 1
                out.append(f'<a class="offsite" href="{m.group(1)}" target="_blank" '
                           f'rel="noopener">{m.group(2)} &middot; open &rarr;</a>')
        out.append(body[pos:])
        return "".join(out)

    def to_html(self, body):
        """WP stored HTML with bare newlines for paragraphs. Keep its own markup."""
        body = re.sub(r"<script.*?</script>", "", body, flags=re.S | re.I)
        out, buf = [], []
        BLOCK = re.compile(r"^\s*<(?:/?(?:p|div|ul|ol|li|h[1-6]|figure|blockquote|table|tr|td|iframe|embed|object)\b|!--)", re.I)
        for line in body.split("\n"):
            if BLOCK.match(line) or line.strip().startswith(("<figure", "<div class=\"gallery", "</div>")):
                if buf:
                    out.append("<p>" + "<br>".join(buf) + "</p>")
                    buf = []
                out.append(line)
            elif line.strip() == "":
                if buf:
                    out.append("<p>" + "<br>".join(buf) + "</p>")
                    buf = []
            else:
                buf.append(line.strip())
        if buf:
            out.append("<p>" + "<br>".join(buf) + "</p>")
        h = "\n".join(out)
        h = re.sub(r"<p>\s*</p>", "", h)
        return h.strip()

    def to_md(self, body):
        """Markdown for GitHub. Images already rewritten to ../images/ by expand()."""
        b = body
        b = re.sub(r'<figcaption>(.*?)</figcaption>', lambda m: f"\n*{re.sub(r'<[^>]+>','',m.group(1)).strip()}*\n", b, flags=re.S | re.I)
        b = re.sub(r'<h3 class="gallery-h">(.*?)</h3>', r"\n**\1**\n", b, flags=re.S | re.I)
        b = re.sub(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']*)["\'][^>]*>', r"![\2](\1)", b, flags=re.I)
        b = re.sub(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>', r"![](\1)", b, flags=re.I)
        def _link(m):
            # Square brackets inside the label break the link syntax - escape them.
            lbl = re.sub(r"<[^>]+>", "", m.group(2)).strip() or m.group(1)
            lbl = lbl.replace("[", r"\[").replace("]", r"\]")
            return f"[{lbl}]({m.group(1)})"
        b = re.sub(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', _link, b, flags=re.S | re.I)
        b = re.sub(r"<(strong|b)>(.*?)</\1>", r"**\2**", b, flags=re.S | re.I)
        b = re.sub(r"<(em|i)>(.*?)</\1>", r"*\2*", b, flags=re.S | re.I)
        b = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>",
                   lambda m: "\n\n" + "#" * min(6, int(m.group(1)) + 1) + " " + m.group(2).strip() + "\n\n", b, flags=re.S | re.I)
        b = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: "\n- " + m.group(1).strip(), b, flags=re.S | re.I)
        b = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>",
                   lambda m: "\n\n" + "\n".join("> " + l for l in re.sub(r"<[^>]+>", "", m.group(1)).strip().split("\n")) + "\n\n", b, flags=re.S | re.I)
        b = re.sub(r"<br\s*/?>", "\n", b, flags=re.I)
        b = re.sub(r"</p>", "\n\n", b, flags=re.I)
        b = re.sub(r"<[^>]+>", "", b)
        b = html.unescape(b)
        b = re.sub(r"[ \t]+", " ", b)
        b = re.sub(r"\n[ \t]+", "\n", b)
        b = re.sub(r"\n{3,}", "\n\n", b)
        return b.strip()

    # -- main ---------------------------------------------------------------
    def run(self):
        rows = self.con.execute("""
            SELECT ID,post_date,post_title,post_content,post_name,post_author,
                   post_type,post_status,comment_count
            FROM wp_posts
            WHERE post_type IN ('post','page') AND post_status IN ('publish','private')
            ORDER BY post_date""").fetchall()
        index = []
        for ID, date, title, content, pname, author, ptype, pstatus, ccount in rows:
            slug = slugify(title, pname)
            d = date[:10]
            name = f"{d}-{slug}"

            html_body, imgs_h = self.expand(content or "", "")
            html_body = self.to_html(html_body)
            md_body, imgs_m = self.expand(content or "", "../")
            md_body = self.to_md(md_body)

            extras = []
            seen = {i["raw"] for i in imgs_h}
            for aid in self.att_parent.get(str(ID), []):
                p = self.attached.get(aid)
                if not p:
                    continue
                p = "wp-content/uploads/" + p
                if not self.exists(p):
                    continue
                dest = self.adopt(p)
                if dest in seen:
                    continue
                seen.add(dest)
                cap = self.alt.get(aid) or self.att_title.get(aid) or ""
                extras.append({"src": dest, "cap": cap,
                               "file": bool(re.search(r"\.(pdf|zip|docx?)$", dest, re.I))})

            stored_author = self.users.get(author, str(author))
            fix = self.attrib.get(str(ID))
            author_name = fix["signed_by"] if fix else stored_author
            attrib_note = ""
            if fix:
                who = self.attrib_author.get("full", fix["signed_by"])
                uid = self.attrib_author.get("wp_user_id")
                attrib_note = (
                    f"> **Authorship corrected.** This post is stored in the WordPress database "
                    f"under the `{stored_author}` account, but it is not {stored_author}'s. "
                    f"{who}'s account (`wp_users.ID={uid}`) was deleted and her posts were "
                    f"reassigned, which rewrote `post_author` on every one of them. "
                    f"Evidence: {fix['evidence']}")
            # Excerpt: prose only - drop image syntax, unwrap links, drop headings.
            ex = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md_body)      # images
            ex = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", ex)         # links -> text
            ex = re.sub(r"^\s*#{1,6}\s*", "", ex, flags=re.M)         # headings
            ex = re.sub(r"[*_`>]", "", ex)
            ex = re.sub(r"\s+", " ", ex).strip()
            text_only = re.sub(r"\s+", " ", md_body)
            excerpt = (ex[:240] + "…") if len(ex) > 240 else ex

            # ---- markdown file
            md = [f"# {title or '(untitled)'}", "",
                  f"**{'Page' if ptype == 'page' else 'Post'}** · {d} · by `{author_name}`"
                  + (f" · status: {pstatus}" if pstatus != "publish" else "")
                  + (f" · {ccount} comments" if ccount and str(ccount) != "0" else "")
                  + f" · `wp_posts.ID={ID}`", ""]
            if attrib_note:
                md += [attrib_note, ""]
            md += ["---", "",
                  md_body if md_body.strip() else "*(no body text in the archive)*"]
            if extras:
                md += ["", "---", "", "### Attached media", ""]
                for e in extras:
                    md.append(f"- [{e['cap'] or os.path.basename(e['src'])}](../{e['src']}) (file)"
                              if e["file"] else f"![{e['cap']}](../{e['src']})")
            md += ["", "---", "", "[← archive index](../README.md)"]
            open(os.path.join(ROOT, "posts", name + ".md"), "w").write("\n".join(md) + "\n")

            # ---- html fragment
            frag = [html_body or '<p class="note">(no body text in the archive)</p>']
            if extras:
                frag.append('<h3 class="gallery-h">Attached media</h3><div class="gallery">')
                for e in extras:
                    if e["file"]:
                        frag.append(f'<p><a href="{e["src"]}" target="_blank" rel="noopener">'
                                    f'{html.escape(e["cap"] or os.path.basename(e["src"]))}</a> (file)</p>')
                    else:
                        frag.append(f'<figure><a href="{e["src"]}" target="_blank" rel="noopener">'
                                    f'<img loading="lazy" src="{e["src"]}" alt="{html.escape(e["cap"])}"></a>'
                                    + (f'<figcaption>{html.escape(e["cap"])}</figcaption>' if e["cap"] else "")
                                    + "</figure>")
                frag.append("</div>")
            open(os.path.join(ROOT, "data", "html", name + ".html"), "w").write("\n".join(frag) + "\n")

            thumb = None
            for i in imgs_h:
                t = self.thumb_of(i["raw"])
                if t:
                    thumb = t
                    break
            index.append({"slug": name, "date": d, "title": title or "(untitled)",
                          "author": author_name, "stored_author": stored_author,
                          "attribution": (fix["confidence"] if fix else None),
                          "type": ptype, "status": pstatus,
                          "comments": int(ccount or 0), "wp_id": str(ID),
                          "images": len([i for i in imgs_h if not i["raw"].lower().endswith(".pdf")]),
                          "thumb": thumb, "excerpt": excerpt, "words": len(text_only.split())})
            self.stats["files"] += 1

        meta = {"generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
                "posts": len([i for i in index if i["type"] == "post"]),
                "pages": len([i for i in index if i["type"] == "page"]),
                "images": len(self.copied),
                "first": min(i["date"] for i in index),
                "last": max(i["date"] for i in index),
                "authors": collections.Counter(i["author"] for i in index if i["type"] == "post").most_common()}
        json.dump({"meta": meta, "items": index},
                  open(os.path.join(ROOT, "data", "posts.json"), "w"), indent=1)
        print(json.dumps(dict(self.stats), indent=1))
        print(json.dumps(meta, indent=1)[:600])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--skip-images", action="store_true")
    a = ap.parse_args()
    if not a.source:
        sys.exit("give --source /path/to/wordpress-export (or set WP_SOURCE); it must\n"
                 "contain heatsynclabs-wp.sql and the www.heatsynclabs.org/ tree")
    if not os.path.isdir(os.path.join(a.source, "www.heatsynclabs.org")):
        sys.exit(f"source not found: {a.source}")
    for d in ("posts", "data/html"):
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)
    Builder(a.source, a.skip_images).run()
