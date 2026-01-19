from __future__ import annotations

import io
from typing import Any, Dict, Optional

from flask import Flask, render_template_string, request
from pypdf import PdfReader

app = Flask(__name__)

TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PDF Metadata Viewer</title>
    <style>
      :root {
        --bg: #f6f3ec;
        --fg: #1a1a1a;
        --accent: #a24d2f;
        --card: #fffaf1;
        --muted: #6b625a;
      }
      body {
        margin: 0;
        font-family: "Georgia", "Times New Roman", serif;
        background: var(--bg);
        color: var(--fg);
      }
      .wrap {
        max-width: 980px;
        margin: 0 auto;
        padding: 32px 20px 60px;
      }
      header {
        margin-bottom: 18px;
      }
      h1 {
        font-size: 32px;
        margin: 0 0 8px;
        letter-spacing: 0.5px;
      }
      p {
        margin: 0;
        color: var(--muted);
      }
      form {
        margin: 18px 0 28px;
        display: grid;
        gap: 10px;
      }
      .card {
        background: var(--card);
        border: 1px solid #e2d8c7;
        border-radius: 12px;
        padding: 16px;
      }
      input[type="file"] {
        padding: 8px;
      }
      button {
        width: 180px;
        padding: 10px 14px;
        border: none;
        border-radius: 8px;
        background: var(--accent);
        color: white;
        font-weight: 600;
        cursor: pointer;
      }
      button:hover {
        filter: brightness(0.95);
      }
      .grid {
        display: grid;
        gap: 12px;
      }
      .grid-2 {
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      }
      dl {
        margin: 0;
      }
      dt {
        font-weight: 700;
        margin-top: 8px;
      }
      dd {
        margin: 2px 0 0 0;
        color: var(--muted);
        word-break: break-word;
      }
      pre {
        background: #1f1b16;
        color: #f0e6d8;
        padding: 14px;
        border-radius: 10px;
        overflow: auto;
        max-height: 420px;
      }
      .error {
        color: #8b1c1c;
        font-weight: 600;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <header>
        <h1>PDF Metadata Viewer</h1>
        <p>Upload a PDF to view parsed fields and raw metadata.</p>
      </header>

      <form method="post" enctype="multipart/form-data" class="card">
        <input type="file" name="pdf" accept="application/pdf" />
        <button type="submit">Extract Metadata</button>
      </form>

      {% if error %}
        <p class="error">{{ error }}</p>
      {% endif %}

      {% if result %}
        <section class="grid grid-2">
          <div class="card">
            <h2>Parsed Fields</h2>
            <dl>
              {% for key, value in result.parsed.items() %}
                <dt>{{ key }}</dt>
                <dd>{{ value if value else "-" }}</dd>
              {% endfor %}
            </dl>
          </div>
          <div class="card">
            <h2>File Summary</h2>
            <dl>
              <dt>Filename</dt>
              <dd>{{ result.filename }}</dd>
              <dt>File Size (bytes)</dt>
              <dd>{{ result.size_bytes }}</dd>
              <dt>Pages</dt>
              <dd>{{ result.page_count }}</dd>
            </dl>
          </div>
        </section>

        <section class="card">
          <h2>Raw PDF Info Dictionary</h2>
          <pre>{{ result.raw_info }}</pre>
        </section>

        <section class="card">
          <h2>XMP Metadata (raw XML)</h2>
          <pre>{{ result.xmp_xml if result.xmp_xml else "No XMP metadata found." }}</pre>
        </section>
      {% endif %}
    </div>
  </body>
</html>
"""


def to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    return str(value)


def extract_xmp_xml(xmp: Any) -> Optional[str]:
    if not xmp:
        return None
    for attr in ("get_xml", "xml", "xmpmeta"):
        candidate = getattr(xmp, attr, None)
        if callable(candidate):
            try:
                xml = candidate()
                return to_str(xml)
            except Exception:
                continue
        if candidate is not None:
            return to_str(candidate)
    return None


def build_parsed_fields(info: Dict[str, str], xmp: Any) -> Dict[str, str]:
    fields = {
        "Title": info.get("/Title", ""),
        "Author": info.get("/Author", ""),
        "Subject": info.get("/Subject", ""),
        "Keywords": info.get("/Keywords", ""),
        "Creator": info.get("/Creator", ""),
        "Producer": info.get("/Producer", ""),
        "CreationDate": info.get("/CreationDate", ""),
        "ModDate": info.get("/ModDate", ""),
        "Trapped": info.get("/Trapped", ""),
    }

    if xmp:
        xmp_map = {
            "Title (XMP)": "dc_title",
            "Creator (XMP)": "dc_creator",
            "Description (XMP)": "dc_description",
            "Keywords (XMP)": "pdf_keywords",
            "CreatorTool (XMP)": "xmp_creatortool",
            "CreateDate (XMP)": "xmp_create_date",
            "ModifyDate (XMP)": "xmp_modify_date",
            "Producer (XMP)": "pdf_producer",
        }
        for label, attr in xmp_map.items():
            val = getattr(xmp, attr, None)
            if val is not None:
                fields[label] = to_str(val)

    return fields


@app.route("/", methods=["GET", "POST"])
def index():
    error = ""
    result = None

    if request.method == "POST":
        upload = request.files.get("pdf")
        if not upload or not upload.filename:
            error = "Please choose a PDF file."
        else:
            try:
                data = upload.read()
                reader = PdfReader(io.BytesIO(data))
                info = reader.metadata or {}
                info_dict = {to_str(k): to_str(v) for k, v in info.items()}
                xmp = reader.xmp_metadata
                result = {
                    "filename": upload.filename,
                    "size_bytes": len(data),
                    "page_count": len(reader.pages),
                    "parsed": build_parsed_fields(info_dict, xmp),
                    "raw_info": to_str(info_dict),
                    "xmp_xml": extract_xmp_xml(xmp),
                }
            except Exception as exc:
                error = f"Failed to read PDF metadata: {exc}"

    return render_template_string(TEMPLATE, result=result, error=error)


if __name__ == "__main__":
    app.run(debug=True)
