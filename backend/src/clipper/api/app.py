"""
App factory and entry point.

  clipper-server        ->  http://127.0.0.1:8000

  /api/...      JSON API
  /media/clips  generated clips (data/clips)
  /media/backgrounds  background videos (data/backgrounds)
  /             built frontend (frontend/out), if present
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from clipper import __version__, config
from clipper.api.routes import backgrounds, jobs, library, search, system


def create_app() -> FastAPI:
    app = FastAPI(title="Clipper", version=__version__)
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                       allow_methods=["*"], allow_headers=["*"])

    for router in (system.router, search.router, jobs.router, library.router, backgrounds.router):
        app.include_router(router, prefix="/api")

    for folder in (config.CLIPS_DIR, config.BACKGROUNDS_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    app.mount("/media/clips", StaticFiles(directory=config.CLIPS_DIR), name="clips")
    app.mount("/media/backgrounds", StaticFiles(directory=config.BACKGROUNDS_DIR), name="backgrounds")

    # Must be mounted last: it catches every path not matched above.
    if config.FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="ui")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    url = f"http://{config.API_HOST}:{config.API_PORT}"
    if config.FRONTEND_DIST.exists():
        print(f"Clipper UI: {url}")
    else:
        print(f"API running at {url}/api. Build the UI with `npm run build` in frontend/, "
              "or run `npm run dev` there.")
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)


if __name__ == "__main__":
    main()
