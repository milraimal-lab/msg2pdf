"""Command-line interface (useful for scripting / testing).

    python -m msg2pdf --cli a.msg b.msg folder/ -o emails.pdf [--sort date] [--split-every 100]
"""

import argparse
import os

from . import converter

SORTS = {
    "date": converter.sort_key_date,
    "subject": lambda i: i.subject.lower(),
    "sender": lambda i: i.sender.lower(),
    "file": lambda i: os.path.basename(i.path).lower(),
    "attachments": lambda i: i.attachment_count,
}


def collect(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                files += [os.path.join(root, n) for n in sorted(names) if n.lower().endswith(".msg")]
        else:
            files.append(p)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(prog="msg2pdf", description="Combine .msg emails into one PDF.")
    ap.add_argument("inputs", nargs="+", help=".msg files and/or folders")
    ap.add_argument("-o", "--output", required=True, help="output PDF")
    ap.add_argument("--sort", choices=["none", *SORTS], default="none",
                    help="order of the emails (default: as given)")
    ap.add_argument("--reverse", action="store_true", help="reverse the order")
    ap.add_argument("--paper", choices=list(converter.PAGE_SIZES), default="A4")
    ap.add_argument("--landscape", action="store_true")
    ap.add_argument("--no-toc", action="store_true", help="omit the contents page")
    ap.add_argument("--no-page-numbers", action="store_true")
    ap.add_argument("--no-bookmarks", action="store_true")
    ap.add_argument("--no-embed", action="store_true", help="list attachments without embedding them")
    ap.add_argument("--split-every", type=int, default=0, metavar="N",
                    help="start a new PDF every N emails")
    ap.add_argument("--split-mb", type=float, default=0, metavar="MB",
                    help="start a new PDF before one would exceed MB megabytes")
    args = ap.parse_args(argv)

    files = collect(args.inputs)
    if args.sort != "none":
        infos = [converter.read_info(f) for f in files]
        infos.sort(key=SORTS[args.sort])
        files = [i.path for i in infos]
    if args.reverse:
        files.reverse()

    opts = converter.Options(
        paper=args.paper,
        landscape=args.landscape,
        include_toc=not args.no_toc,
        page_numbers=not args.no_page_numbers,
        bookmarks=not args.no_bookmarks,
        embed_attachments=not args.no_embed,
        split_every=args.split_every,
        split_max_mb=args.split_mb,
    )

    def progress(done, total, text):
        print(f"[{done}/{total}] {text}")

    result = converter.convert(files, args.output, opts, progress=progress)
    for w in result.warnings:
        print("WARNING:", w)
    for f in result.files:
        print("Wrote", f)
    return 0
