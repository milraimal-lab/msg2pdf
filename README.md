# msg2pdf

Combine a batch of Outlook **.msg** emails into **one PDF**. Each email's
attachments are **embedded in the PDF**, so you click an attachment to open it.

## Features

- **Add emails:** use **Add files…** or **Add folder…**, or drag .msg files in
  from Explorer/Finder.
- **Set the order before converting:**
  - **Drag rows** up and down. You can drag several selected rows at once.
  - Use **▲ Move up** / **▼ Move down**, or Ctrl+↑ / Ctrl+↓.
  - **Click a column heading** (Sent, From, Subject, Attach., File) to sort.
    Click it again to reverse the order.
- **Each email in the PDF** starts on a new page. It shows the subject, From,
  Sent, To and Cc, then the attachment list and the message body. HTML,
  plain-text and RTF bodies all work, and inline images are included.
- **Attachments:** a 📎 paperclip icon sits next to each attachment name.
  Click or double-click it to open or save the file. Attachments also appear
  in your PDF viewer's *Attachments* panel. Attached emails (.msg inside .msg)
  are embedded too.
- **Navigation:** an optional clickable **Contents** page at the front, and a
  **bookmark** for each email.
- **Other options:** A4 or Letter pages.

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

From a Python command prompt (e.g. *WinPython Command Prompt*), in this folder:

```bash
build.bat
```

The program will be in `dist\msg2pdf.exe`.

### Command line (optional)

```bash
python -m msg2pdf --cli emails_folder -o emails.pdf --sort date
```

## Limitations

- Remote images, the ones an email loads from the internet, are not
  downloaded. Their alt text is shown instead.
- Very complex HTML layouts, such as newsletters, may not look exactly like
  they do in Outlook.
