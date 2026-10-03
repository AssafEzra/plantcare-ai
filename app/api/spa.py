"""Serve the built React application from the API process.

DEPLOYMENT §3 draws the UI and the API as two services. One container serving both
is the collapsed form of that, and it is collapsed along a different seam than the
Streamlit deployment was: there, the API ran inside the UI's process and the two
spoke over loopback. Here the UI is a directory of static files with no process at
all, and the only thing shared is an origin.

Sharing the origin is not an accident of hosting - it is what the frontend was
written against. `VITE_API_BASE_URL` is empty (`frontend/.env.example:9`), so
`frontend/src/lib/api.ts` asks for a relative `/v1/...`; there is no CORS
middleware anywhere in `app/`; and the service worker's `navigateFallbackDenylist`
is `/^\\/v1\\//`, the same prefix every router is mounted under. A second host
would need all three of those decisions reversed.

What this module adds is the one thing a static directory cannot do for itself: a
single-page application has no file at `/plants/<id>`, but a reader who refreshes
that page must still get the application rather than a 404. So an unmatched path
returns `index.html` and lets the router in the browser read the URL.

The careful part is what `index.html` must *not* answer for. `/v1/does-not-exist`
is a wrong API call and has to stay a `NOT_FOUND` envelope, because a client
parsing JSON would otherwise receive a page of HTML and report something
incomprehensible. `RESERVED` is that list, and it is asserted on in
`tests/api/test_spa.py`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.common.errors import NotFoundError

#: Paths that belong to the API and must never be answered with the application
#: shell. A request under one of these that matches no route is a 404 in the
#: API_CONTRACTS envelope, exactly as it was before the SPA shared the origin.
RESERVED = ("/v1", "/livez", "/readyz", "/docs", "/openapi.json")

#: Vite hashes everything it emits into `assets/` (`index-OjgYu6z4.js`), so the
#: name changes whenever the content does and a stale copy is never asked for
#: again. A year is the convention; the upper bound is what matters, not the value.
_IMMUTABLE = "public, max-age=31536000, immutable"

#: Everything else. `index.html` names the current bundle and the service worker
#: decides when to replace itself, so both have to be revalidated every time - a
#: cached `sw.js` pins a visitor to the shell it shipped with, which is the one
#: caching mistake that cannot be fixed by deploying again.
_NO_CACHE = "no-cache"


def mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve `dist` as the application, with its deep links intact.

    Must be called last. Starlette matches in registration order, so the
    catch-all below would shadow any route registered after it.

    One handler rather than a `StaticFiles` mount for `assets/` plus a fallback.
    The mount was the first shape of this and it quietly dropped the only thing it
    existed for: `StaticFiles` sets `ETag` and `Last-Modified` but no
    `Cache-Control`, so the hashed bundles - the only files here worth caching
    hard - were revalidated on every navigation.
    """
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        # A built directory without an index is a broken build, not an empty one,
        # and failing here names the problem while the deployment logs are being
        # read. Serving a 404 for every page would not.
        raise RuntimeError(f"SPA_DIST_DIR has no index.html: {dist}")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        """Return a real file when there is one, and the shell when there is not."""
        if f"/{full_path}".startswith(RESERVED):
            raise NotFoundError()

        candidate = (dist / full_path).resolve()
        # `is_relative_to` after `resolve` is the traversal guard: `..%2f..%2f.env`
        # resolves out of `dist`, fails this test, and falls through to the shell
        # rather than reading a file the deployment never meant to publish.
        if full_path and candidate.is_relative_to(dist) and candidate.is_file():
            hashed = candidate.parent == dist / "assets"
            return FileResponse(
                candidate,
                headers={"Cache-Control": _IMMUTABLE if hashed else _NO_CACHE},
            )

        # A missing *asset* is a 404, not the shell. Everything under `assets/` is
        # requested by `index.html` as a script or a stylesheet, and answering one
        # of those with a page of HTML produces a syntax error in the console
        # instead of the missing file's name.
        if full_path.startswith("assets/"):
            raise NotFoundError()

        return FileResponse(index, headers={"Cache-Control": _NO_CACHE})
