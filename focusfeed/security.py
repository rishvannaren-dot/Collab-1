"""Security headers for every response.

The Content-Security-Policy only lets the browser run Focus Feed's own script
file and the one inline theme script (marked with a per-request nonce), load
its own styles and fonts, and show YouTube thumbnails. Anything injected into
a page would be blocked.
"""

import secrets

from flask import g, request

CSP = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self'; "
    "font-src 'self'; "
    "img-src 'self' https://i.ytimg.com; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def init_app(app):
    @app.before_request
    def make_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def inject_nonce():
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.after_request
    def add_headers(response):
        headers = response.headers
        headers["Content-Security-Policy"] = CSP.format(nonce=getattr(g, "csp_nonce", ""))
        headers["X-Content-Type-Options"] = "nosniff"
        headers["Referrer-Policy"] = "same-origin"
        headers["X-Frame-Options"] = "DENY"
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), browsing-topics=()"
        # Signed-in pages aren't kept in the browser's cache, so pressing Back on a
        # shared computer after logging out doesn't show the student's pages.
        if getattr(g, "user", None) is not None and not request.path.startswith("/static/"):
            headers.setdefault("Cache-Control", "no-store")
        return response
