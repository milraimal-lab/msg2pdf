"""Tkinter GUI for msg2pdf.

* Add .msg files with the buttons, or drag them in from Explorer/Finder
  (needs the optional `tkinterdnd2` package).
* Order: pick a "Sort by" mode, click a column heading, or drag rows / use the
  Move buttons for a manual order.
* Options: page size, orientation, contents page, page numbers, bookmarks,
  embedding attachments, splitting into several PDFs.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, converter

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAVE_DND = True
except Exception:  # optional dependency
    HAVE_DND = False


COLUMNS = (
    ("num", "#", 45, "e"),
    ("date", "Sent", 125, "w"),
    ("sender", "From", 180, "w"),
    ("subject", "Subject", 330, "w"),
    ("atts", "Attach.", 60, "center"),
    ("file", "File", 200, "w"),
)
SORT_KEYS = {
    "date": converter.sort_key_date,
    "sender": lambda i: i.sender.lower(),
    "subject": lambda i: i.subject.lower(),
    "atts": lambda i: i.attachment_count,
    "file": lambda i: os.path.basename(i.path).lower(),
}
MANUAL = "Manual order (drag rows)"
SORT_MODES = {  # label -> (column, ascending)
    MANUAL: None,
    "Date – oldest first": ("date", True),
    "Date – newest first": ("date", False),
    "Subject A–Z": ("subject", True),
    "Subject Z–A": ("subject", False),
    "From A–Z": ("sender", True),
    "From Z–A": ("sender", False),
    "File name A–Z": ("file", True),
    "File name Z–A": ("file", False),
    "Most attachments first": ("atts", False),
}
DEFAULT_SORT = "Date – oldest first"

SPLIT_NONE = "Don't split – one PDF"
SPLIT_COUNT = "New PDF every N emails"
SPLIT_SIZE = "New PDF before N MB"
SPLIT_MODES = (SPLIT_NONE, SPLIT_COUNT, SPLIT_SIZE)

DEFAULT_SETTINGS = {
    "sort": DEFAULT_SORT,
    "paper": "A4",
    "orientation": "Portrait",
    "toc": True,
    "page_numbers": True,
    "bookmarks": True,
    "embed": True,
    "open_after": True,
    "split_mode": SPLIT_NONE,
    "split_count": 100,
    "split_mb": 25,
    "last_dir": "",
}


def settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "msg2pdf", "settings.json")


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            stored = json.load(fh)
        settings.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    except Exception:
        pass
    return settings


def save_settings(settings: dict) -> None:
    try:
        path = settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
    except Exception:
        pass


def open_path(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        messagebox.showerror("Open", f"Could not open:\n{path}\n\n{exc}")


def _human_size(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class Cancelled(Exception):
    pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"MSG to PDF {__version__}")
        root.geometry("1050x680")
        root.minsize(800, 480)

        self.settings = load_settings()
        self.items: dict[str, converter.EmailInfo] = {}  # tree iid -> info
        self.sizes: dict[str, int] = {}  # tree iid -> file size on disk
        self.queue: queue.Queue = queue.Queue()
        self.loading = 0
        self.busy = False
        self.cancel_event = threading.Event()
        self._drag = None  # state while dragging rows

        self._build_ui()
        self._update_heading_arrows()
        self._update_status()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        s = self.settings

        # --- toolbar ---------------------------------------------------------
        top = ttk.Frame(self.root, padding=(8, 8, 8, 0))
        top.pack(fill="x")
        ttk.Button(top, text="Add files…", command=self.add_files_dialog).pack(side="left")
        ttk.Button(top, text="Add folder…", command=self.add_folder_dialog).pack(side="left", padx=(4, 0))
        ttk.Button(top, text="Remove", command=self.remove_selected).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Clear", command=self.clear).pack(side="left", padx=(4, 0))
        ttk.Button(top, text="▲ Up", width=6, command=lambda: self.move_selected(-1)).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="▼ Down", width=7, command=lambda: self.move_selected(1)).pack(side="left", padx=(4, 0))

        self.sort_mode = tk.StringVar(value=s["sort"] if s["sort"] in SORT_MODES else DEFAULT_SORT)
        sort_box = ttk.Combobox(top, textvariable=self.sort_mode, values=list(SORT_MODES),
                                state="readonly", width=24)
        sort_box.pack(side="right")
        sort_box.bind("<<ComboboxSelected>>", lambda e: self.apply_sort())
        ttk.Label(top, text="Sort by:").pack(side="right", padx=(0, 4))

        # --- list ------------------------------------------------------------
        mid = ttk.Frame(self.root, padding=(8, 6, 8, 0))
        mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=[c[0] for c in COLUMNS], show="headings", selectmode="extended")
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title, command=lambda k=key: self.heading_clicked(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=key in ("subject", "file", "sender"))
        self.tree.tag_configure("error", foreground="#b00000")
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        hint = "Drag rows to reorder (switches to manual order) · Delete removes · Ctrl+↑/↓ moves"
        if HAVE_DND:
            hint = "Drop .msg files or folders here · " + hint
        ttk.Label(self.root, text=hint, foreground="#666", padding=(8, 2, 8, 0)).pack(fill="x")

        self.tree.bind("<ButtonPress-1>", self._on_press)
        self.tree.bind("<B1-Motion>", self._on_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_release)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<Control-Up>", lambda e: (self.move_selected(-1), "break")[1])
        self.tree.bind("<Control-Down>", lambda e: (self.move_selected(1), "break")[1])
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])

        if HAVE_DND:
            for widget in (self.tree, self.root):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_file_drop)

        # --- options -----------------------------------------------------------
        opts = ttk.LabelFrame(self.root, text="Options", padding=(8, 4, 8, 6))
        opts.pack(fill="x", padx=8, pady=(6, 0))

        row1 = ttk.Frame(opts)
        row1.pack(fill="x")
        ttk.Label(row1, text="Page size:").pack(side="left")
        self.paper = tk.StringVar(value=s["paper"] if s["paper"] in converter.PAGE_SIZES else "A4")
        ttk.Combobox(row1, textvariable=self.paper, values=list(converter.PAGE_SIZES), width=7,
                     state="readonly").pack(side="left", padx=(4, 12))
        self.orientation = tk.StringVar(value=s["orientation"])
        ttk.Combobox(row1, textvariable=self.orientation, values=["Portrait", "Landscape"], width=10,
                     state="readonly").pack(side="left", padx=(0, 16))

        self.toc = tk.BooleanVar(value=s["toc"])
        self.page_numbers = tk.BooleanVar(value=s["page_numbers"])
        self.bookmarks = tk.BooleanVar(value=s["bookmarks"])
        self.embed = tk.BooleanVar(value=s["embed"])
        self.open_after = tk.BooleanVar(value=s["open_after"])
        for text, var in (
            ("Contents page", self.toc),
            ("Page numbers", self.page_numbers),
            ("Bookmarks", self.bookmarks),
            ("Embed attachments", self.embed),
            ("Open when finished", self.open_after),
        ):
            ttk.Checkbutton(row1, text=text, variable=var).pack(side="left", padx=(0, 12))

        row2 = ttk.Frame(opts)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="Split output:").pack(side="left")
        self.split_mode = tk.StringVar(value=s["split_mode"] if s["split_mode"] in SPLIT_MODES else SPLIT_NONE)
        split_box = ttk.Combobox(row2, textvariable=self.split_mode, values=SPLIT_MODES, state="readonly", width=24)
        split_box.pack(side="left", padx=(4, 6))
        split_box.bind("<<ComboboxSelected>>", lambda e: self._update_split_widgets())
        self.split_count = tk.IntVar(value=int(s["split_count"]))
        self.split_mb = tk.IntVar(value=int(s["split_mb"]))
        self.split_spin = ttk.Spinbox(row2, from_=1, to=100000, width=7)
        self.split_spin.pack(side="left")
        self.split_unit = ttk.Label(row2, text="")
        self.split_unit.pack(side="left", padx=(4, 0))
        self.split_spin.bind("<KeyRelease>", lambda e: self._store_split_value())
        self.split_spin.configure(command=self._store_split_value)
        self._update_split_widgets()

        # --- bottom bar ------------------------------------------------------
        bottom = ttk.Frame(self.root, padding=8)
        bottom.pack(fill="x")
        self.status = tk.StringVar()
        ttk.Label(bottom, textvariable=self.status).pack(side="left")
        self.convert_btn = ttk.Button(bottom, text="Convert to PDF…", command=self.convert)
        self.convert_btn.pack(side="right")
        self.cancel_btn = ttk.Button(bottom, text="Cancel", command=self.cancel)
        self.progress = ttk.Progressbar(bottom, length=220, mode="determinate")
        self.progress.pack(side="right", padx=8)

    def _update_split_widgets(self):
        mode = self.split_mode.get()
        self.split_spin.delete(0, "end")
        if mode == SPLIT_COUNT:
            self.split_spin.state(["!disabled"])
            self.split_spin.insert(0, str(self.split_count.get()))
            self.split_unit.configure(text="emails per PDF")
        elif mode == SPLIT_SIZE:
            self.split_spin.state(["!disabled"])
            self.split_spin.insert(0, str(self.split_mb.get()))
            self.split_unit.configure(text="MB max per PDF (e.g. 25 for email)")
        else:
            self.split_spin.state(["disabled"])
            self.split_unit.configure(text="")

    def _store_split_value(self):
        try:
            value = max(1, int(float(self.split_spin.get())))
        except ValueError:
            return
        if self.split_mode.get() == SPLIT_COUNT:
            self.split_count.set(value)
        elif self.split_mode.get() == SPLIT_SIZE:
            self.split_mb.set(value)

    def _collect_settings(self) -> dict:
        self._store_split_value()
        self.settings.update(
            sort=self.sort_mode.get(),
            paper=self.paper.get(),
            orientation=self.orientation.get(),
            toc=self.toc.get(),
            page_numbers=self.page_numbers.get(),
            bookmarks=self.bookmarks.get(),
            embed=self.embed.get(),
            open_after=self.open_after.get(),
            split_mode=self.split_mode.get(),
            split_count=self.split_count.get(),
            split_mb=self.split_mb.get(),
        )
        return self.settings

    def _on_close(self):
        if self.busy and not messagebox.askyesno("Conversion running", "A conversion is running. Quit anyway?"):
            return
        save_settings(self._collect_settings())
        self.root.destroy()

    # ----------------------------------------------------------- adding ----
    def add_files_dialog(self):
        paths = filedialog.askopenfilenames(
            title="Choose Outlook emails",
            initialdir=self.settings.get("last_dir") or None,
            filetypes=[("Outlook messages", "*.msg"), ("All files", "*.*")],
        )
        if paths:
            self.settings["last_dir"] = os.path.dirname(paths[0])
        self.add_paths(paths)

    def add_folder_dialog(self):
        folder = filedialog.askdirectory(title="Choose a folder containing .msg files",
                                         initialdir=self.settings.get("last_dir") or None)
        if folder:
            self.settings["last_dir"] = folder
            self.add_paths([folder])

    def _on_file_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))
        return event.action

    def add_paths(self, paths):
        if self.busy:
            return
        files = []
        for p in paths:
            if os.path.isdir(p):
                for root, _dirs, names in os.walk(p):
                    files += [os.path.join(root, n) for n in sorted(names) if n.lower().endswith(".msg")]
            elif os.path.isfile(p) and p.lower().endswith(".msg"):
                files.append(p)
        existing = {os.path.normcase(os.path.abspath(i.path)) for i in self.items.values()}
        new = []
        for f in files:
            key = os.path.normcase(os.path.abspath(f))
            if key not in existing:
                existing.add(key)
                new.append(f)
        if not new:
            if paths:
                self.status.set("No new .msg files found.")
            return
        # Insert placeholders immediately, fill in details in the background.
        iids = []
        for f in new:
            info = converter.EmailInfo(path=f, subject="(reading…)")
            iid = self.tree.insert("", "end", values=self._row_values(info))
            self.items[iid] = info
            try:
                self.sizes[iid] = os.path.getsize(f)
            except OSError:
                self.sizes[iid] = 0
            iids.append((iid, f))
        self.loading += len(iids)
        self._renumber()
        threading.Thread(target=self._load_worker, args=(iids,), daemon=True).start()

    def _load_worker(self, iids):
        for iid, path in iids:
            info = converter.read_info(path)
            self.queue.put(("loaded", iid, info))

    # ---------------------------------------------------------- list ops ---
    def _row_values(self, info: converter.EmailInfo, num: int = 0):
        subject = info.subject if not info.error else f"⚠ could not read: {info.error}"
        return (num, info.date_text, info.sender, subject,
                info.attachment_count or "", os.path.basename(info.path))

    def _refresh_row(self, iid):
        info = self.items[iid]
        num = self.tree.index(iid) + 1
        self.tree.item(iid, values=self._row_values(info, num), tags=("error",) if info.error else ())

    def _renumber(self):
        for n, iid in enumerate(self.tree.get_children(), 1):
            self.tree.set(iid, "num", n)
        self._update_status()

    def _update_status(self):
        if self.busy:
            return
        count = len(self.items)
        if self.loading:
            self.status.set(f"Reading {self.loading} of {count} file(s)…")
        elif count == 0:
            self.status.set("Add .msg files to begin (buttons above, or drag them in).")
        else:
            size = _human_size(sum(self.sizes.values()))
            self.status.set(f"{count} email(s), {size} of .msg files.")

    def remove_selected(self):
        if self.busy:
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.items.pop(iid, None)
            self.sizes.pop(iid, None)
        self._renumber()

    def clear(self):
        if self.busy:
            return
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self.sizes.clear()
        self._renumber()

    def move_selected(self, delta: int):
        sel = list(self.tree.selection())
        if not sel or self.busy:
            return
        selected = set(sel)
        order = list(self.tree.get_children())
        indices = range(1, len(order)) if delta < 0 else range(len(order) - 2, -1, -1)
        for i in indices:
            j = i + delta  # neighbour position
            if order[i] in selected and order[j] not in selected:
                order[i], order[j] = order[j], order[i]
        self._apply_order(order)
        visible = [iid for iid in order if iid in selected]
        self.tree.see(visible[0] if delta < 0 else visible[-1])
        self._set_manual()
        self._renumber()

    def _apply_order(self, order):
        for n, iid in enumerate(order):
            self.tree.move(iid, "", n)

    # --------------------------------------------------------------- sort --
    def apply_sort(self):
        mode = SORT_MODES.get(self.sort_mode.get())
        if mode:
            column, ascending = mode
            key = SORT_KEYS[column]
            ordered = sorted(self.tree.get_children(), key=lambda iid: key(self.items[iid]),
                             reverse=not ascending)
            self._apply_order(ordered)
            self._renumber()
        self._update_heading_arrows()

    def heading_clicked(self, column: str):
        if column not in SORT_KEYS:
            return
        current = SORT_MODES.get(self.sort_mode.get())
        ascending = not (current and current[0] == column and current[1])
        if current is None or current[0] != column:
            ascending = column != "atts"  # sensible first direction
        for label, mode in SORT_MODES.items():
            if mode == (column, ascending):
                self.sort_mode.set(label)
                break
        else:
            # direction not offered in the drop-down: sort once, then manual
            key = SORT_KEYS[column]
            ordered = sorted(self.tree.get_children(), key=lambda iid: key(self.items[iid]),
                             reverse=not ascending)
            self._apply_order(ordered)
            self._set_manual()
            self._renumber()
            return
        self.apply_sort()

    def _set_manual(self):
        if self.sort_mode.get() != MANUAL:
            self.sort_mode.set(MANUAL)
            self._update_heading_arrows()

    def _update_heading_arrows(self):
        mode = SORT_MODES.get(self.sort_mode.get())
        for k, title, *_ in COLUMNS:
            arrow = ""
            if mode and mode[0] == k:
                arrow = " ▲" if mode[1] else " ▼"
            self.tree.heading(k, text=title + arrow)

    # ----------------------------------------------- drag to reorder rows --
    def _on_press(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            self._drag = None
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            self._drag = None
            return None
        modifiers = event.state & 0x0005  # Shift / Control
        self._drag = {"row": row, "moved": False, "y": event.y}
        if row in self.tree.selection() and not modifiers:
            # Keep a multi-row selection so it can be dragged as a group.
            return "break"
        return None

    def _on_motion(self, event):
        if not self._drag or self.busy:
            return
        if not self._drag["moved"] and abs(event.y - self._drag["y"]) < 4:
            return
        self._drag["moved"] = True
        self.tree.configure(cursor="sb_v_double_arrow")
        # auto-scroll near the edges
        height = self.tree.winfo_height()
        if event.y < 15:
            self.tree.yview_scroll(-1, "units")
        elif event.y > height - 15:
            self.tree.yview_scroll(1, "units")

        target = self.tree.identify_row(event.y)
        if not target:
            return
        sel = list(self.tree.selection()) or [self._drag["row"]]
        if target in sel:
            return
        children = list(self.tree.get_children())
        sel_sorted = sorted(sel, key=children.index)
        target_idx = children.index(target)
        remaining = [c for c in children if c not in sel]
        insert_at = remaining.index(target)
        if target_idx > children.index(sel_sorted[0]):
            insert_at += 1  # dragging downwards: drop after target
        self._apply_order(remaining[:insert_at] + sel_sorted + remaining[insert_at:])
        self._set_manual()

    def _on_release(self, event):
        drag, self._drag = self._drag, None
        self.tree.configure(cursor="")
        if not drag:
            return
        if drag["moved"]:
            self._renumber()
        elif not (event.state & 0x0005):
            # plain click on an already-selected row: select just that row
            self.tree.selection_set(drag["row"])
            self.tree.focus(drag["row"])

    # ------------------------------------------------------------ convert --
    def _options(self) -> converter.Options:
        self._store_split_value()
        mode = self.split_mode.get()
        return converter.Options(
            paper=self.paper.get(),
            landscape=self.orientation.get() == "Landscape",
            include_toc=self.toc.get(),
            page_numbers=self.page_numbers.get(),
            bookmarks=self.bookmarks.get(),
            embed_attachments=self.embed.get(),
            split_every=self.split_count.get() if mode == SPLIT_COUNT else 0,
            split_max_mb=self.split_mb.get() if mode == SPLIT_SIZE else 0,
        )

    def convert(self):
        if self.busy:
            return
        if self.loading:
            messagebox.showinfo("Please wait", "Still reading the files, try again in a moment.")
            return
        order = list(self.tree.get_children())
        if not order:
            messagebox.showinfo("Nothing to convert", "Add some .msg files first.")
            return
        opts = self._options()
        out = filedialog.asksaveasfilename(
            title="Save PDF as", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialdir=self.settings.get("last_dir") or None, initialfile="emails.pdf",
        )
        if not out:
            return
        save_settings(self._collect_settings())
        paths = [self.items[iid].path for iid in order]
        self.busy = True
        self.cancel_event.clear()
        self.convert_btn.state(["disabled"])
        self.cancel_btn.pack(side="right", before=self.progress)
        self.progress.configure(maximum=len(paths), value=0)
        threading.Thread(target=self._convert_worker, args=(paths, out, opts), daemon=True).start()

    def cancel(self):
        if self.busy:
            self.cancel_event.set()
            self.status.set("Cancelling…")

    def _convert_worker(self, paths, out, opts):
        def progress(done, total, text):
            if self.cancel_event.is_set():
                raise Cancelled()
            self.queue.put(("progress", done, total, text))

        try:
            result = converter.convert(paths, out, opts, progress=progress)
            self.queue.put(("done", result))
        except Cancelled:
            self.queue.put(("cancelled",))
        except Exception as exc:
            self.queue.put(("failed", str(exc) or exc.__class__.__name__))

    # ------------------------------------------------------- queue pump ---
    def _poll_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "loaded":
                    _, iid, info = msg
                    self.loading -= 1
                    if iid in self.items:
                        self.items[iid] = info
                        self._refresh_row(iid)
                    if self.loading == 0:
                        self.apply_sort()  # keep the chosen order as files arrive
                        self._renumber()
                    elif self.loading % 25 == 0:
                        self._update_status()
                elif kind == "progress":
                    _, done, total, text = msg
                    self.progress.configure(maximum=max(total, 1), value=done)
                    self.status.set(text)
                elif kind == "done":
                    self._finish()
                    self._show_result(msg[1])
                elif kind == "cancelled":
                    self._finish()
                    self.status.set("Cancelled.")
                    messagebox.showinfo("Cancelled", "The conversion was cancelled.\n"
                                        "Parts that were already finished have been kept.")
                elif kind == "failed":
                    self._finish()
                    self.status.set("Conversion failed.")
                    messagebox.showerror("Conversion failed", msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _show_result(self, result: converter.Result):
        files = result.files
        self.status.set(f"Done: {len(files)} PDF(s), {result.pages} pages.")
        lines = [f"{result.emails} emails → {len(files)} PDF file(s), {result.pages} pages:"]
        for f in files[:12]:
            try:
                size = _human_size(os.path.getsize(f))
            except OSError:
                size = "?"
            lines.append(f"  {os.path.basename(f)}  ({size})")
        if len(files) > 12:
            lines.append(f"  …and {len(files) - 12} more")
        lines.append(f"\nFolder: {os.path.dirname(files[0])}")
        if result.warnings:
            lines.append(f"\nWarnings ({len(result.warnings)}):")
            lines += [f"  {w}" for w in result.warnings[:12]]
            if len(result.warnings) > 12:
                lines.append(f"  …and {len(result.warnings) - 12} more")
        if self.open_after.get():
            open_path(files[0] if len(files) == 1 else os.path.dirname(files[0]))
        messagebox.showinfo("Done", "\n".join(lines))

    def _finish(self):
        self.busy = False
        self.convert_btn.state(["!disabled"])
        self.cancel_btn.pack_forget()
        self.progress.configure(value=0)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = TkinterDnD.Tk() if HAVE_DND else tk.Tk()
    try:
        ttk.Style(root).theme_use("vista" if sys.platform.startswith("win") else "clam")
    except tk.TclError:
        pass
    app = App(root)
    if argv:
        app.add_paths(argv)
    root.mainloop()


if __name__ == "__main__":
    main()
