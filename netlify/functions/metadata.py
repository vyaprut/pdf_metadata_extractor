import base64
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pypdf import PdfReader


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    return str(value)


def _extract_xmp_xml(xmp: Any) -> Optional[str]:
    if not xmp:
        return None
    for attr in ("get_xml", "xml", "xmpmeta"):
        candidate = getattr(xmp, attr, None)
        if callable(candidate):
            try:
                xml = candidate()
                return _to_str(xml)
            except Exception:
                continue
        if candidate is not None:
            return _to_str(candidate)
    return None


def _build_parsed_fields(info: Dict[str, str], xmp: Any) -> Dict[str, str]:
    def to_ist(date_str: str) -> str:
        if not date_str:
            return ""
        if date_str.startswith("D:"):
            date_str = date_str[2:]
        # Basic PDF date parser: YYYYMMDDHHmmSSOHH'mm'
        def _digits(s: str, n: int) -> Optional[int]:
            if len(s) < n or not s[:n].isdigit():
                return None
            return int(s[:n])

        y = _digits(date_str, 4)
        mo = _digits(date_str[4:], 2) if y is not None else None
        d = _digits(date_str[6:], 2) if mo is not None else None
        hh = _digits(date_str[8:], 2) if d is not None else 0
        mm = _digits(date_str[10:], 2) if d is not None else 0
        ss = _digits(date_str[12:], 2) if d is not None else 0
        if y is None or mo is None or d is None:
            return _to_str(date_str)

        tz = timezone.utc
        tz_part = date_str[14:]
        if tz_part:
            sign = tz_part[0]
            if sign in ("+", "-"):
                try:
                    tzh = int(tz_part[1:3])
                    tzm = int(tz_part[4:6]) if len(tz_part) >= 6 else 0
                    offset = timedelta(hours=tzh, minutes=tzm)
                    if sign == "-":
                        offset = -offset
                    tz = timezone(offset)
                except Exception:
                    tz = timezone.utc
        try:
            dt = datetime(y, mo, d, hh, mm, ss, tzinfo=tz)
        except Exception:
            return _to_str(date_str)
        ist = timezone(timedelta(hours=5, minutes=30))
        return dt.astimezone(ist).strftime("%Y-%m-%d %H:%M:%S %Z")

    fields = {
        "Title": info.get("/Title", ""),
        "Author": info.get("/Author", ""),
        "Subject": info.get("/Subject", ""),
        "Keywords": info.get("/Keywords", ""),
        "Creator": info.get("/Creator", ""),
        "Producer": info.get("/Producer", ""),
        "CreationDate (IST)": to_ist(info.get("/CreationDate", "")),
        "ModDate (IST)": to_ist(info.get("/ModDate", "")),
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
                fields[label] = _to_str(val)

    return fields


def _response(status: int, body: Dict[str, Any]):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
        "body": json.dumps(body),
    }


def handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {"ok": True})

    if event.get("httpMethod") != "POST":
        return _response(405, {"error": "Use POST"})

    try:
        raw_body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw_body = base64.b64decode(raw_body).decode("utf-8", errors="replace")
        payload = json.loads(raw_body)
    except Exception:
        return _response(400, {"error": "Invalid JSON body"})

    file_b64 = payload.get("file_base64")
    filename = payload.get("filename") or "upload.pdf"
    if not file_b64:
        return _response(400, {"error": "Missing file_base64"})

    try:
        pdf_bytes = base64.b64decode(file_b64)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        info = reader.metadata or {}
        info_dict = {_to_str(k): _to_str(v) for k, v in info.items()}
        xmp = reader.xmp_metadata
        result = {
            "filename": filename,
            "size_bytes": len(pdf_bytes),
            "page_count": len(reader.pages),
            "parsed": _build_parsed_fields(info_dict, xmp),
            "raw_info": info_dict,
            "xmp_xml": _extract_xmp_xml(xmp),
        }
        return _response(200, {"ok": True, "result": result})
    except Exception as exc:
        return _response(400, {"error": f"Failed to read PDF metadata: {exc}"})
