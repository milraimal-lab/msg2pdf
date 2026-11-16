"""Tkinter GUI for msg2pdf.

* Add .msg files with the buttons, or drag them in from Explorer/Finder
  (needs the optional `tkinterdnd2` package).
* Reorder by dragging rows, with the Move up/down buttons (Ctrl+Up/Down), or by
  clicking a column heading to sort.
* Convert -> pick the output PDF.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import converter

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAVE_DND = True
except Exception:  # optional dependency
    HAVE_DND = False


COLUMNS = (
    ("num", "#", 40, "e"),
    ("date", "Sent", 130, "w"),
    ("sender", "From", 180, "w"),
    ("subject", "Subject", 320, "w"),
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


def open_file(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        messagebox.showerror("Open PDF", f"Could not open the PDF:\n{exc}")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("MSG to PDF")
        root.geometry("1000x600")
        root.minsize(700, 400)

        self.items: dict[str, converter.EmailInfo] = {}  # tree iid -> info
        self.queue: queue.Queue = queue.Queue()
        self.loading = 0
        self.busy = False
        self.sort_state: dict[str, bool] = {}
        self._drag = None  # state while dragging rows

        self._build_ui()
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(8, 8, 8, 0))
        top.pack(fill="x")
        ttk.Button(top, text="Add files…", command=self.add_files_dialog).pack(side="left")
        ttk.Button(top, text="Add folder…", command=self.add_folder_dialog).pack(side="left", padx=(4, 0))
        ttk.Button(top, text="Remove", command=self.remove_selected).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Clear", command=self.clear).pack(side="left", padx=(4, 0))
        ttk.Button(top, text="▲ Move up", command=lambda: self.move_selected(-1)).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="▼ Move down", command=lambda: self.move_selected(1)).pack(side="left", padx=(4, 0))

        hint = "Drag rows to reorder · click a column heading to sort"
        if HAVE_DND:
            hint = "Drop .msg files here · " + hint
        ttk.Label(top, text=hint, foreground="#666").pack(side="right")

        mid = ttk.Frame(self.root, padding=8)
        mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=[c[0] for c in COLUMNS], show="headings", selectmode="extended")
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=key in ("subject", "file", "sender"))
        self.tree.tag_configure("error", foreground="#b00000")
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Row drag & drop reordering
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

        bottom = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        bottom.pack(fill="x")
        ttk.Label(bottom, text="Page size:").pack(side="left")
        self.paper = tk.StringVar(value="A4")
        ttk.Combobox(bottom, textvariable=self.paper, values=list(converter.PAGE_SIZES), width=7,
                     state="readonly").pack(side="left", padx=(4, 12))
        self.toc = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="Contents page", variable=self.toc).pack(side="left")

        self.convert_btn = ttk.Button(bottom, text="Convert to PDF…", command=self.convert)
        self.convert_btn.pack(side="right")
        self.progress = ttk.Progressbar(bottom, length=200, mode="determinate")
        self.progress.pack(side="right", padx=8)
        self.status = tk.StringVar(value="Add .msg files to begin.")
        ttk.Label(bottom, textvariable=self.status).pack(side="left", padx=(16, 0))

    # ----------------------------------------------------------- adding ----
    def add_files_dialog(self):
        paths = filedialog.askopenfilenames(
            title="Choose Outlook emails",
            filetypes=[("Outlook messages", "*.msg"), ("All files", "*.*")],
        )
        self.add_paths(paths)

    def add_folder_dialog(self):
        folder = filedialog.askdirectory(title="Choose a folder containing .msg files")
        if folder:
            self.add_paths([folder])

    def _on_file_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))
        return event.action

    def add_paths(self, paths):
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
        # Insert placeholders immediately (keeps the order), fill details in background.
        iids = []
        for f in new:
            info = converter.EmailInfo(path=f, subject="(reading…)")
            iid = self.tree.insert("", "end", values=self._row_values(info))
            self.items[iid] = info
            iids.append((iid, f))
        self.loading += len(iids)
        self._renumber()
        self.status.set(f"Reading {self.loading} file(s)…")
        threading.Thread(target=self._load_worker, args=(iids,), daemon=True).start()

    def _load_worker(self, iids):
        for iid, path in iids:
            info = converter.read_info(path)
            self.queue.put(("loaded", iid, info))

    # ---------------------------------------------------------- list ops ---
    def _row_values(self, info: converter.EmailInfo, num: int = 0):
        subject = info.subject if not info.error else f"⚠ {info.error}"
        return (num, info.date_text, info.sender, subject,
                info.attachment_count or "", os.path.basename(info.path))

    def _refresh_row(self, iid):
        info = self.items[iid]
        num = self.tree.index(iid) + 1
        self.tree.item(iid, values=self._row_values(info, num), tags=("error",) if info.error else ())

    def _renumber(self):
        for n, iid in enumerate(self.tree.get_children(), 1):
            self.tree.set(iid, "num", n)
        count = len(self.items)
        if not self.busy and not self.loading:
            self.status.set(f"{count} email(s). Drag to reorder, then Convert.")

    def remove_selected(self):
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.items.pop(iid, None)
        self._renumber()

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self._renumber()

    def move_selected(self, delta: int):
        sel = list(self.tree.selection())
        if not sel:
            return
        selected = set(sel)
        order = list(self.tree.get_children())
        indices = range(1, len(order)) if delta < 0 else range(len(order) - 2, -1, -1)
        for i in indices:
            j = i + delta  # neighbour position
            if order[i] in selected and order[j] not in selected:
                order[i], order[j] = order[j], order[i]
        for n, iid in enumerate(order):
            self.tree.move(iid, "", n)
        visible = [iid for iid in order if iid in selected]
        self.tree.see(visible[0] if delta < 0 else visible[-1])
        self._clear_sort_arrows()
        self._renumber()

    def sort_by(self, column: str):
        if column not in SORT_KEYS:
            return
        ascending = not self.sort_state.get(column, False)
        self.sort_state = {column: ascending}
        key = SORT_KEYS[column]
        ordered = sorted(self.tree.get_children(), key=lambda iid: key(self.items[iid]), reverse=not ascending)
        for n, iid in enumerate(ordered):
            self.tree.move(iid, "", n)
        for k, title, *_ in COLUMNS:
            arrow = (" ▲" if ascending else " ▼") if k == column else ""
            self.tree.heading(k, text=title + arrow)
        self._renumber()

    def _clear_sort_arrows(self):
        self.sort_state = {}
        for k, title, *_ in COLUMNS:
            self.tree.heading(k, text=title)

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
        for offset, iid in enumerate(sel_sorted):
            self.tree.move(iid, "", insert_at + offset)
        self._clear_sort_arrows()

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
        out = filedialog.asksaveasfilename(
            title="Save PDF as", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile="emails.pdf",
        )
        if not out:
            return
        paths = [self.items[iid].path for iid in order]
        self.busy = True
        self.convert_btn.state(["disabled"])
        self.progress.configure(maximum=len(paths), value=0)
        threading.Thread(
            target=self._convert_worker,
            args=(paths, out, self.paper.get(), self.toc.get()),
            daemon=True,
        ).start()

    def _convert_worker(self, paths, out, paper, toc):
        def progress(done, total, text):
            self.queue.put(("progress", done, total, text))

        try:
            warnings = converter.convert(paths, out, paper=paper, include_toc=toc, progress=progress)
            self.queue.put(("done", out, warnings))
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
                        self._renumber()
                elif kind == "progress":
                    _, done, total, text = msg
                    self.progress.configure(maximum=max(total, 1), value=done)
                    self.status.set(text)
                elif kind == "done":
                    _, out, warnings = msg
                    self._finish()
                    self.status.set(f"Saved {os.path.basename(out)}")
                    text = f"PDF created:\n{out}"
                    if warnings:
                        shown = "\n".join(warnings[:15])
                        more = f"\n…and {len(warnings) - 15} more" if len(warnings) > 15 else ""
                        text += f"\n\nWarnings:\n{shown}{more}"
                    if messagebox.askyesno("Done", text + "\n\nOpen the PDF now?"):
                        open_file(out)
                elif kind == "failed":
                    self._finish()
                    self.status.set("Conversion failed.")
                    messagebox.showerror("Conversion failed", msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _finish(self):
        self.busy = False
        self.convert_btn.state(["!disabled"])
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
