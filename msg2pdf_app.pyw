"""Launcher for msg2pdf (also the entry point of the Windows .exe).

    msg2pdf.exe                      -> opens the window
    msg2pdf.exe a.msg b.msg          -> opens the window with these files added
    msg2pdf.exe --cli <args>         -> command-line conversion (see msg2pdf/cli.py)
    msg2pdf.exe --selftest <file>    -> opens and closes the window, writes "ok" to <file>
"""

import os
import sys


def _ensure_streams():
    # A windowed .exe has no console, so stdout/stderr are None.
    if sys.stdout is None or sys.stderr is None:
        sink = open(os.devnull, "w")
        sys.stdout = sys.stdout or sink
        sys.stderr = sys.stderr or sink


def run():
    _ensure_streams()
    args = sys.argv[1:]
    if args and args[0] == "--cli":
        from msg2pdf.cli import main as cli_main

        return cli_main(args[1:])
    if args and args[0] == "--selftest":
        return _selftest(args[1] if len(args) > 1 else "selftest.txt", args[2] if len(args) > 2 else None)
    from msg2pdf.app import main as gui_main

    gui_main(args)
    return 0


def _selftest(report_path, folder=None):
    """Build the real window, exercise it, close it, and report the result.

    With `folder`, also loads its .msg files and checks sorting, moving rows
    and the option widgets, all through the real GUI objects.
    """
    import traceback

    notes = []
    errors = []

    try:
        from msg2pdf import app

        root = app.TkinterDnD.Tk() if app.HAVE_DND else app.tk.Tk()
        gui = app.App(root)

        def check(cond, what):
            (notes if cond else errors).append(("ok   " if cond else "FAIL ") + what)

        def exercise():
            try:
                tree = gui.tree
                rows = list(tree.get_children())
                check(len(rows) > 0, f"loaded {len(rows)} files")
                for label in app.SORT_MODES:
                    gui.sort_mode.set(label)
                    gui.apply_sort()
                gui.sort_mode.set("Date – oldest first")
                gui.apply_sort()
                order = [gui.items[i] for i in tree.get_children()]
                dated = [i.date.timestamp() for i in order if i.date]
                check(dated == sorted(dated), "date sort is ascending")
                gui.heading_clicked("date")
                check(gui.sort_mode.get() == "Date – newest first", "heading click toggles to newest first")
                first = tree.get_children()[0]
                tree.selection_set(first)
                gui.move_selected(1)
                check(tree.index(first) == 1, "move down works")
                check(gui.sort_mode.get() == app.MANUAL, "manual order after moving")
                for mode in app.SPLIT_MODES:
                    gui.split_mode.set(mode)
                    gui._update_split_widgets()
                gui.split_mode.set(app.SPLIT_COUNT)
                gui._update_split_widgets()
                opts = gui._options()
                check(opts.split_every > 0, "split option reaches converter")
                nums = [int(tree.set(i, "num")) for i in tree.get_children()]
                check(nums == list(range(1, len(nums) + 1)), "rows numbered 1..N")
            except Exception:
                errors.append(traceback.format_exc())
            root.destroy()

        def wait_for_load(tries=0):
            if gui.loading and tries < 600:
                root.after(100, wait_for_load, tries + 1)
            else:
                exercise()

        if folder:
            gui.add_paths([folder])
            root.after(300, wait_for_load)
        else:
            root.after(1500, root.destroy)
        root.mainloop()
        code = 1 if errors else 0
        result = ("ok" if not errors else "FAILED") + f" dnd={app.HAVE_DND}\n" + "\n".join(notes + errors)
    except Exception:
        result = "FAILED\n" + traceback.format_exc()
        code = 1
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(result)
    return code


if __name__ == "__main__":
    sys.exit(run())
