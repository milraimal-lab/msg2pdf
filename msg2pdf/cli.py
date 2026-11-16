"""Command-line interface (useful for scripting / testing).

    python -m msg2pdf --cli a.msg b.msg folder/ -o emails.pdf [--sort date] [--paper Letter]
"""

import argparse
import os

from . import converter


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
    ap.add_argument("--sort", choices=["none", "date", "subject", "sender", "file"], default="none",
                    help="order of the emails (default: as given)")
    ap.add_argument("--reverse", action="store_true", help="reverse the sort order")
    ap.add_argument("--paper", choices=list(converter.PAGE_SIZES), default="A4")
    ap.add_argument("--no-toc", action="store_true", help="omit the contents page")
    args = ap.parse_args(argv)

    files = collect(args.inputs)
    if args.sort != "none":
        infos = [converter.read_info(f) for f in files]
        keys = {
            "date": converter.sort_key_date,
            "subject": lambda i: i.subject.lower(),
            "sender": lambda i: i.sender.lower(),
            "file": lambda i: os.path.basename(i.path).lower(),
        }
        infos.sort(key=keys[args.sort], reverse=args.reverse)
        files = [i.path for i in infos]
    elif args.reverse:
        files.reverse()

    def progress(done, total, text):
        print(f"[{done}/{total}] {text}")

    warnings = converter.convert(files, args.output, paper=args.paper,
                                 include_toc=not args.no_toc, progress=progress)
    for w in warnings:
        print("WARNING:", w)
    print("Wrote", args.output)
    return 0
