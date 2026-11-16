# PyInstaller build recipe:  python -m PyInstaller --noconfirm --clean msg2pdf.spec
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []
for pkg in ("tkinterdnd2", "extract_msg", "RTFDE"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["msg2pdf_app.pyw"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["msg2pdf.app", "msg2pdf.cli", "msg2pdf.converter"],
    excludes=["pymupdf4llm", "pymupdf_layout", "matplotlib", "numpy", "pandas", "PIL", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="msg2pdf",
    console=False,  # windowed app, no black console window
    upx=False,
)
