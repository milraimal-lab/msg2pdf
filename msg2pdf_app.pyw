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
        return _selftest(args[1] if len(args) > 1 else "selftest.txt")
    from msg2pdf.app import main as gui_main

    gui_main(args)
    return 0


def _selftest(report_path):
    """Build the real window, close it after a moment, and report the result."""
    import traceback

    try:
        from msg2pdf import app

        root = app.TkinterDnD.Tk() if app.HAVE_DND else app.tk.Tk()
        app.App(root)
        root.after(1500, root.destroy)
        root.mainloop()
        result = f"ok dnd={app.HAVE_DND}"
        code = 0
    except Exception:
        result = "FAILED\n" + traceback.format_exc()
        code = 1
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(result)
    return code


if __name__ == "__main__":
    sys.exit(run())
