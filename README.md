# msg2pdf

Combine a batch of Outlook **.msg** emails into **one PDF**. Each email's
attachments are **embedded in the PDF**, so you click an attachment to open it.

## Features

- **Add emails:** use **Add files…** or **Add folder…**, or drag .msg files in
  from Explorer/Finder.
- **Set the order before converting:**
  - **Sort by** drop-down: Date (oldest or newest first), Subject, From, File
    name, or Most attachments. The default is *Date – oldest first*, and files
    you add later are sorted in automatically.
  - **Click a column heading** to sort by it. Click again to reverse.
  - **Drag rows** up and down, or use **▲ Up** / **▼ Down** (Ctrl+↑ / Ctrl+↓).
    This switches to *Manual order*. You can drag several selected rows at
    once.
- **Each email in the PDF** starts on a new page. It shows the subject, From,
  Sent, To and Cc, then the attachment list and the message body. HTML,
  plain-text and RTF bodies all work, and inline images are included.
- **Attachments:** a 📎 paperclip icon sits next to each attachment name.
  Click or double-click it to open or save the file. Attachments also appear
  in your PDF viewer's *Attachments* panel. Attached emails (.msg inside .msg)
  are embedded too.
- **Options** (remembered between runs):
  - **Page size:** A4, Letter or Legal, portrait or landscape.
  - **Contents page:** a clickable list of every email at the front.
  - **Page numbers:** a "Page X of Y" footer.
  - **Bookmarks:** one per email, in the viewer's sidebar.
  - **Embed attachments:** turn this off for a much smaller PDF that only
    lists the attachment names.
  - **Open when finished.**
  - **Split output:** start a new PDF every *N* emails, or before a file would
    exceed *N* MB (e.g. 25 MB to stay under email limits). The parts are saved
    as `name_part01.pdf`, `name_part02.pdf`, … Each part has its own contents
    page, which shows which emails it holds.
- **Cancel** stops a long conversion. Parts that are already finished are
  kept.

### How many emails?

There is no fixed limit. In a test, **506 emails** (136 MB of .msg files)
became a single 898-page, 153 MB PDF in about 1½ minutes, using about 300 MB of
memory. That works out to roughly 6 emails per second.

The output is about as big as all the attachments combined. For thousands of
emails, or emails with very large attachments, use **Split output**. Each part
is written to disk and freed before the next one starts, so memory use stays
low however many emails you add.

> Use a viewer that supports PDF attachments: **Adobe Acrobat Reader**,
> **Foxit**, **PDF-XChange**, or **Firefox**. Some viewers, such as the
> Chrome/Edge built-in viewer, may show the paperclip without letting you open
> the file.

## Download (Windows, no Python needed)

Download **msg2pdf.exe** from the
[latest release](https://github.com/milraimal-lab/msg2pdf/releases/tag/latest)
and double-click it. Every push to `main` rebuilds and tests the .exe.

Windows SmartScreen may warn about an unknown publisher, because the .exe
isn't code-signed. Click **More info → Run anyway**.

## Install and run from source

1. Install Python 3.9 or newer from <https://python.org>.
2. In this folder, run:

   ```bash
   pip install -r requirements.txt
   ```

3. Start the app by double-clicking `msg2pdf_app.pyw`, or run:

   ```bash
   python -m msg2pdf
   ```

### Build the .exe yourself (optional)

Double-click `build.bat`. It finds a WinPython folder next to this one (e.g. `F:\Py\WPy64-…`), or Python on PATH. Or run it from a Python command prompt:

```bash
build.bat
```

The program will be in `dist\msg2pdf.exe`.

### Command line (optional)

```bash
python -m msg2pdf --cli emails_folder -o emails.pdf --sort date
```

The .exe accepts the same arguments (`msg2pdf.exe --cli ...`). Other options:
`--reverse`, `--paper A4|Letter|Legal`, `--landscape`, `--no-toc`,
`--no-page-numbers`, `--no-bookmarks`, `--no-embed`, `--split-every N`,
`--split-mb N`.

## Limitations

- Remote images, the ones an email loads from the internet, are not
  downloaded. Their alt text is shown instead.
- Very complex HTML layouts, such as newsletters, may not look exactly like
  they do in Outlook.
