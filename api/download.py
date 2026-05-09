# -*- coding: utf-8 -*-
"""
GET /api/download?token=<token>
מגיש את ה-PDF השמור ב-_PDF_CACHE של search.py כ-attachment.
המשתמש מוריד ישירות מהדומיין שלו – ללא הפניה לאתר חיצוני.
"""
import json, logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ייבוא ה-cache המשותף מ-search.py
from search import _PDF_CACHE, _evict_old

log = logging.getLogger(__name__)

class handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        _evict_old()
        qs    = parse_qs(urlparse(self.path).query)
        token = (qs.get("token") or [""])[0].strip()

        if not token or token not in _PDF_CACHE:
            self._err(404, "קישור ההורדה פג תוקף או לא תקין. חפש שוב.")
            return

        entry    = _PDF_CACHE.pop(token)   # single-use
        pdf_data = entry["data"]
        filename = entry["filename"]

        # encode filename for Content-Disposition (RFC 5987)
        try:
            ascii_name = filename.encode("ascii").decode()
            cd = f'attachment; filename="{ascii_name}"'
        except UnicodeEncodeError:
            encoded = filename.encode("utf-8").hex()
            cd = f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type",        "application/pdf")
        self.send_header("Content-Length",      str(len(pdf_data)))
        self.send_header("Content-Disposition", cd)
        self.send_header("Cache-Control",       "no-store")
        self.end_headers()
        self.wfile.write(pdf_data)
        log.info("Served PDF %s (%d bytes)", filename, len(pdf_data))

    def _err(self, code, msg):
        body = json.dumps({"success": False, "error": msg},
                          ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info(fmt, *args)
