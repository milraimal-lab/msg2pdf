"""Core conversion logic: Outlook .msg files -> one PDF with embedded attachments.

Each email is rendered as HTML (header block + body) with PyMuPDF's Story
engine.  Every attachment is embedded in the PDF as a "file attachment"
annotation (a paperclip icon) next to its name in the email header, so clicking
it in a PDF viewer opens / saves the original file.
"""

from __future__ import annotations

import html
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import extract_msg
import fitz  # PyMuPDF

try:
    from bs4 import BeautifulSoup
except ImportError:  # bs4 is a dependency of extract-msg, but be defensive
    BeautifulSoup = None


PAGE_SIZES = {"A4": "a4", "Letter": "letter"}
MARGIN = 40  # points
ICON_SIZE = 12  # points, paperclip icon


# --------------------------------------------------------------------------- #
# Reading .msg files
# --------------------------------------------------------------------------- #
@dataclass
class AttachmentData:
    filename: str
    data: Optional[bytes]  # None if it could not be extracted
    content_id: Optional[str] = None
    note: str = ""  # e.g. reason it could not be embedded


@dataclass
class EmailInfo:
    """Lightweight metadata used by the GUI list (no bodies / attachment data)."""

    path: str
    subject: str = ""
    sender: str = ""
    to: str = ""
    date: Optional[datetime] = None
    attachment_count: int = 0
    error: str = ""

    @property
    def date_text(self) -> str:
        return format_date(self.date)


@dataclass
class EmailContent:
    info: EmailInfo
    cc: str = ""
    html_body: Optional[str] = None
    text_body: str = ""
    attachments: list[AttachmentData] = field(default_factory=list)


def _s(value) -> str:
    """Coerce a possibly-None / bytes value into a clean string."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value).replace("\x00", "").strip()


def _parse_date(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None


def format_date(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    try:
        if value.tzinfo is not None:
            value = value.astimezone()  # show in local time
    except (OSError, ValueError, OverflowError):
        pass
    return value.strftime("%Y-%m-%d %H:%M")


def sort_key_date(info: EmailInfo):
    """Sort key that copes with naive/aware datetimes and missing dates."""
    if info.date is None:
        return (1, 0.0)
    try:
        return (0, info.date.timestamp())
    except (OSError, ValueError, OverflowError):
        return (1, 0.0)


def _open(path: str):
    return extract_msg.openMsg(path)


def _attachment_name(att, index: int) -> str:
    name = None
    for attr in ("longFilename", "shortFilename", "displayName", "name"):
        try:
            name = _s(getattr(att, attr, None))
        except Exception:
            name = None
        if name:
            break
    if not name:
        name = f"attachment_{index + 1}"
    return name


def _embedded_msg_bytes(att) -> Optional[bytes]:
    """Return the raw bytes of an attached email (.msg inside a .msg)."""
    inner = getattr(att, "data", None)
    export = getattr(inner, "exportBytes", None)
    if callable(export):
        try:
            return export()
        except Exception:
            pass
    # Fallback: let extract-msg write it to a temporary folder.
    try:
        with tempfile.TemporaryDirectory() as tmp:
            att.save(customPath=tmp, extractEmbedded=True, skipEmbedded=False)
            for root, _dirs, files in os.walk(tmp):
                for f in files:
                    if f.lower().endswith(".msg"):
                        with open(os.path.join(root, f), "rb") as fh:
                            return fh.read()
    except Exception:
        pass
    return None


def _attachments(msg) -> list[AttachmentData]:
    result = []
    for i, att in enumerate(getattr(msg, "attachments", None) or []):
        name = _attachment_name(att, i)
        cid = None
        for attr in ("contentId", "cid"):
            try:
                cid = _s(getattr(att, attr, None)) or None
            except Exception:
                cid = None
            if cid:
                break
        data = None
        note = ""
        try:
            raw = att.data
        except Exception as exc:  # corrupt attachment stream
            raw = None
            note = f"could not be read ({exc})"
        if isinstance(raw, (bytes, bytearray)):
            data = bytes(raw)
        elif raw is not None:
            # Embedded email (or other embedded object)
            data = _embedded_msg_bytes(att)
            if data is not None and not name.lower().endswith(".msg"):
                name += ".msg"
            if data is None:
                note = "embedded item could not be extracted"
        elif not note:
            note = "no data (link or unsupported attachment type)"
        result.append(AttachmentData(name, data, cid, note))
    return result


def read_info(path: str) -> EmailInfo:
    """Read just the metadata needed to show the file in the list."""
    info = EmailInfo(path=path)
    try:
        with _open(path) as msg:
            info.subject = _s(getattr(msg, "subject", ""))
            info.sender = _s(getattr(msg, "sender", ""))
            info.to = _s(getattr(msg, "to", ""))
            info.date = _parse_date(getattr(msg, "date", None))
            try:
                info.attachment_count = len(getattr(msg, "attachments", None) or [])
            except Exception:
                info.attachment_count = 0
    except Exception as exc:
        info.error = str(exc) or exc.__class__.__name__
    return info


def read_content(path: str) -> EmailContent:
    info = read_info(path)
    content = EmailContent(info=info)
    if info.error:
        return content
    with _open(path) as msg:
        content.cc = _s(getattr(msg, "cc", ""))
        try:
            body = msg.htmlBody
            if body:
                if isinstance(body, bytes):
                    content.html_body = _decode_html(body)
                else:
                    content.html_body = str(body)
        except Exception:
            content.html_body = None
        try:
            content.text_body = _s(getattr(msg, "body", ""))
        except Exception:
            content.text_body = ""
        content.attachments = _attachments(msg)
    return content


def _decode_html(body: bytes) -> str:
    m = re.search(rb'charset\s*=\s*["\']?([A-Za-z0-9_\-]+)', body[:4000])
    enc = m.group(1).decode("ascii", "replace") if m else "utf-8"
    try:
        return body.decode(enc, "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# HTML building
# --------------------------------------------------------------------------- #
BASE_CSS = """
body { font-family: sans-serif; font-size: 10pt; }
.m2p-subject { font-size: 15pt; font-weight: bold; margin: 0 0 6pt 0; }
.m2p-hdr { font-size: 9.5pt; margin-bottom: 4pt; }
.m2p-hdr td { vertical-align: top; padding: 1pt 4pt 1pt 0; }
.m2p-lbl { font-weight: bold; color: #444444; }
.m2p-att td { padding: 1pt 2pt; vertical-align: middle; font-size: 9.5pt; }
.m2p-attname { color: #1a4f9c; }
.m2p-size { color: #777777; }
.m2p-note { color: #a33; }
.m2p-rule { border-bottom: 1px solid #999999; margin: 6pt 0 10pt 0; }
.m2p-plain { font-family: sans-serif; }
.m2p-error { color: #a00; font-weight: bold; }
.m2p-toc-title { font-size: 18pt; font-weight: bold; margin-bottom: 10pt; }
.m2p-toc td { padding: 2pt 6pt 2pt 0; vertical-align: top; font-size: 9.5pt; }
.m2p-toc-subj { color: #1a4f9c; }
"""


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} bytes"


_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}


def _clean_email_html(raw: str, inline: dict[str, str], content_width: float):
    """Return (style_css, body_html) for an email's HTML body.

    * `cid:` image references are rewritten to archive names in `inline`.
    * scripts and remote resources are dropped.
    * oversized widths are clamped so content doesn't run off the page.
    """
    if BeautifulSoup is None:
        body = re.sub(r"(?is)<(script|head).*?</\1>", "", raw)
        return "", body

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "meta", "link", "title", "base", "iframe", "object", "embed"]):
        tag.decompose()

    css = "\n".join(s.get_text() for s in soup.find_all("style"))
    for s in soup.find_all("style"):
        s.decompose()

    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if src.lower().startswith("cid:"):
            key = src[4:].strip("<>").lower()
            if key in inline:
                img["src"] = inline[key]
            else:
                img.decompose()
                continue
        elif src.lower().startswith(("http:", "https:", "data:", "file:")) or not src:
            # Remote images are not downloaded; show the alt text instead.
            alt = img.get("alt")
            if alt:
                img.replace_with(f"[{alt}]")
            else:
                img.decompose()
            continue
        _clamp_width(img, content_width)

    for tag in soup.find_all(["table", "td", "th", "div"]):
        _clamp_width(tag, content_width)

    body = soup.body
    body_html = body.decode_contents() if body is not None else str(soup)
    return css, body_html


def _clamp_width(tag, max_width: float) -> None:
    w = tag.get("width")
    if not w:
        return
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(px)?\s*$", str(w))
    if not m:
        return
    width = float(m.group(1))
    if width > max_width:
        ratio = max_width / width
        tag["width"] = str(int(max_width))
        h = tag.get("height")
        if tag.name == "img" and h:
            hm = re.match(r"\s*(\d+(?:\.\d+)?)", str(h))
            if hm:
                tag["height"] = str(int(float(hm.group(1)) * ratio))


def _text_to_html(text: str) -> str:
    out = html.escape(text).replace("\r\n", "\n").replace("\r", "\n")
    out = re.sub(r"(https?://[^\s<>\"]+)", r'<a href="\1">\1</a>', out)
    # keep runs of spaces / indentation
    out = re.sub(r"  ", " &#160;", out)
    return '<div class="m2p-plain">' + out.replace("\n", "<br/>") + "</div>"


def _build_email_html(content: EmailContent, archive: fitz.Archive, content_width: float):
    """Return (css, html, attachment_ids) for one email.

    attachment_ids maps the HTML element id of each paperclip cell to the
    attachment index it represents.
    """
    info = content.info
    e = html.escape

    # Inline images referenced from the HTML body by Content-ID
    inline: dict[str, str] = {}
    used_inline: set[int] = set()
    if content.html_body:
        for i, att in enumerate(content.attachments):
            if att.content_id and att.data and os.path.splitext(att.filename)[1].lower() in _IMG_EXT:
                key = att.content_id.strip("<>").lower()
                if ("cid:" + key) in content.html_body.lower():
                    name = f"inline_{i}{os.path.splitext(att.filename)[1].lower()}"
                    archive.add(att.data, name)
                    inline[key] = name
                    used_inline.add(i)

    rows = []
    for label, value in (
        ("From", info.sender),
        ("Sent", info.date_text),
        ("To", info.to),
        ("Cc", content.cc),
    ):
        if value:
            rows.append(f'<tr><td class="m2p-lbl">{label}:</td><td>{e(value)}</td></tr>')

    parts = [f'<div class="m2p-subject">{e(info.subject or "(no subject)")}</div>']
    parts.append('<table class="m2p-hdr">' + "".join(rows) + "</table>")

    attachment_ids: dict[str, int] = {}
    listed = [i for i in range(len(content.attachments)) if i not in used_inline]
    if listed:
        att_rows = []
        for i in listed:
            att = content.attachments[i]
            if att.data is not None:
                cell_id = f"m2p-att-{i}"
                attachment_ids[cell_id] = i
                size = f' <span class="m2p-size">({_human_size(len(att.data))})</span>'
                att_rows.append(
                    f'<tr><td id="{cell_id}" width="{ICON_SIZE + 6}">&#160;</td>'
                    f'<td><span class="m2p-attname">{e(att.filename)}</span>{size}</td></tr>'
                )
            else:
                att_rows.append(
                    f'<tr><td width="{ICON_SIZE + 6}">&#160;</td>'
                    f'<td>{e(att.filename)} <span class="m2p-note">({e(att.note)})</span></td></tr>'
                )
        parts.append(
            f'<table class="m2p-hdr"><tr><td class="m2p-lbl">Attachments ({len(listed)}):</td></tr></table>'
            '<table class="m2p-att">' + "".join(att_rows) + "</table>"
        )
    parts.append('<div class="m2p-rule"></div>')

    email_css = ""
    if info.error:
        parts.append(f'<p class="m2p-error">Could not read this file: {e(info.error)}</p>')
    elif content.html_body:
        email_css, body_html = _clean_email_html(content.html_body, inline, content_width)
        parts.append(f"<div>{body_html}</div>")
    elif content.text_body:
        parts.append(_text_to_html(content.text_body))
    else:
        parts.append("<p><i>(empty message)</i></p>")

    page_html = "<html><body>" + "".join(parts) + "</body></html>"
    return email_css, page_html, attachment_ids


# --------------------------------------------------------------------------- #
# PDF rendering
# --------------------------------------------------------------------------- #
def _render_story(page_html: str, css: str, archive, paper: str):
    """Render HTML to a new fitz.Document.  Returns (doc, positions).

    positions: list of (page_index, element_id, Rect) for elements with an id.
    """
    mediabox = fitz.paper_rect(paper)
    where = mediabox + (MARGIN, MARGIN, -MARGIN, -MARGIN)
    story = fitz.Story(html=page_html, user_css=css, archive=archive)
    positions = []

    def rectfn(rect_num, filled):
        return mediabox, where, None

    def positionfn(pos):
        if getattr(pos, "id", None):
            page = getattr(pos, "page_num", getattr(pos, "pagenum", 0))
            positions.append((page, pos.id, fitz.Rect(pos.rect)))

    doc = story.write_with_links(rectfn, positionfn)
    return doc, positions


def _rects_by_id(positions):
    """Merge open/close position events into one rect per (page, id)."""
    merged: dict[str, tuple[int, fitz.Rect]] = {}
    for page, eid, rect in positions:
        if eid in merged:
            p, r = merged[eid]
            if p == page and not rect.is_empty:
                r |= rect
        else:
            merged[eid] = (page, fitz.Rect(rect))
    return merged


def _render_email(content: EmailContent, paper: str):
    archive = fitz.Archive()
    content_width = fitz.paper_rect(paper).width - 2 * MARGIN
    try:
        email_css, page_html, att_ids = _build_email_html(content, archive, content_width)
        doc, positions = _render_story(page_html, BASE_CSS + "\n" + email_css, archive, paper)
    except Exception as exc:
        # Fall back to the plain-text body if the HTML trips up the renderer.
        content.html_body = None
        if not content.text_body:
            content.text_body = f"(The body of this email could not be rendered: {exc})"
        archive = fitz.Archive()
        _css, page_html, att_ids = _build_email_html(content, archive, content_width)
        doc, positions = _render_story(page_html, BASE_CSS, archive, paper)
    return doc, positions, att_ids


def _embed_attachments(out: fitz.Document, page_offset: int, positions, att_ids, content):
    rects = _rects_by_id(positions)
    for cell_id, att_index in att_ids.items():
        if cell_id not in rects:
            continue
        page_index, rect = rects[cell_id]
        att = content.attachments[att_index]
        page = out[page_offset + page_index]
        # Centre the paperclip icon vertically in its table cell.
        y = rect.y0 + max(0.0, (rect.height - ICON_SIZE) / 2)
        icon_rect = fitz.Rect(rect.x0, y, rect.x0 + ICON_SIZE, y + ICON_SIZE)
        ascii_name = att.filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
        annot = page.add_file_annot(
            icon_rect.tl,
            att.data,
            ascii_name,
            ufilename=att.filename,
            desc=f"Attachment: {att.filename}",
            icon="Paperclip",
        )
        try:
            annot.set_rect(icon_rect)
            annot.set_info(title="Attachment", content=att.filename)
            annot.update()
        except Exception:
            pass


def _build_toc_pages(entries, paper: str):
    """entries: list of (EmailInfo, target_page_index_without_toc)."""
    e = html.escape
    rows = []
    for n, (info, _page) in enumerate(entries):
        rows.append(
            f'<tr><td>{n + 1}.</td><td>{e(info.date_text)}</td>'
            f'<td>{e(info.sender)}</td>'
            f'<td id="m2p-toc-{n}"><span class="m2p-toc-subj">{e(info.subject or "(no subject)")}</span></td></tr>'
        )
    page_html = (
        '<html><body><div class="m2p-toc-title">Contents</div>'
        '<table class="m2p-toc"><tr><td class="m2p-lbl">#</td><td class="m2p-lbl">Sent</td>'
        '<td class="m2p-lbl">From</td><td class="m2p-lbl">Subject</td></tr>'
        + "".join(rows)
        + "</table></body></html>"
    )
    return _render_story(page_html, BASE_CSS, None, paper)


ProgressFn = Callable[[int, int, str], None]


def convert(
    paths: list[str],
    output_pdf: str,
    paper: str = "A4",
    include_toc: bool = True,
    progress: Optional[ProgressFn] = None,
) -> list[str]:
    """Convert `paths` (in the given order) into `output_pdf`.

    Returns a list of warning strings (files that failed, attachments that
    could not be embedded, ...).  Raises on fatal errors (e.g. cannot write the
    output file).
    """
    paper = PAGE_SIZES.get(paper, paper)
    warnings: list[str] = []
    out = fitz.open()
    entries = []  # (EmailInfo, start page)
    total = len(paths)

    for n, path in enumerate(paths):
        name = os.path.basename(path)
        if progress:
            progress(n, total, f"Converting {name}")
        try:
            content = read_content(path)
        except Exception as exc:
            content = EmailContent(info=EmailInfo(path=path, subject=name, error=str(exc)))
        if content.info.error:
            warnings.append(f"{name}: {content.info.error}")
            if not content.info.subject:
                content.info.subject = name
        for att in content.attachments:
            if att.data is None:
                warnings.append(f"{name}: attachment '{att.filename}' {att.note}")

        doc, positions, att_ids = _render_email(content, paper)
        start = out.page_count
        out.insert_pdf(doc)
        doc.close()
        _embed_attachments(out, start, positions, att_ids, content)
        entries.append((content.info, start))

    if progress:
        progress(total, total, "Writing PDF")

    toc_pages = 0
    if include_toc and entries:
        toc_doc, toc_positions = _build_toc_pages(entries, paper)
        toc_pages = toc_doc.page_count
        out.insert_pdf(toc_doc, start_at=0)
        toc_doc.close()
        rects = _rects_by_id(toc_positions)
        for n, (_info, start) in enumerate(entries):
            key = f"m2p-toc-{n}"
            if key in rects:
                page_index, rect = rects[key]
                out[page_index].insert_link(
                    {"kind": fitz.LINK_GOTO, "from": rect, "page": start + toc_pages, "to": fitz.Point(0, 0)}
                )

    # Bookmarks (outline) – one per email.
    outline = []
    if toc_pages:
        outline.append([1, "Contents", 1])
    for info, start in entries:
        title = info.subject or os.path.basename(info.path)
        if info.date_text:
            title = f"{info.date_text}  {title}"
        outline.append([1, title, start + toc_pages + 1])
    if outline:
        out.set_toc(outline)

    out.set_metadata({"title": "Emails", "creator": "msg2pdf", "producer": "msg2pdf (PyMuPDF)"})
    out.save(output_pdf, garbage=3, deflate=True)
    out.close()
    if progress:
        progress(total, total, "Done")
    return warnings
