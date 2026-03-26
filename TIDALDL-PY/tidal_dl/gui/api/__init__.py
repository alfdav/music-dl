"""API router aggregation."""
from fastapi import APIRouter

from tidal_dl.gui.api.albums import router as albums_router
from tidal_dl.gui.api.downloads import router as downloads_router
from tidal_dl.gui.api.home import router as home_router
from tidal_dl.gui.api.library import router as library_router
from tidal_dl.gui.api.playback import router as playback_router
from tidal_dl.gui.api.playlists import router as playlists_router
from tidal_dl.gui.api.search import router as search_router
from tidal_dl.gui.api.settings import router as settings_router
from tidal_dl.gui.api.duplicates import router as duplicates_router
from tidal_dl.gui.api.upgrade import router as upgrade_router

api_router = APIRouter()
api_router.include_router(home_router, tags=["home"])
api_router.include_router(search_router, tags=["search"])
api_router.include_router(albums_router, tags=["albums"])
api_router.include_router(playback_router, prefix="/playback", tags=["playback"])
api_router.include_router(library_router, tags=["library"])
api_router.include_router(downloads_router, tags=["downloads"])
api_router.include_router(playlists_router, tags=["playlists"])
api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(duplicates_router, tags=["duplicates"])
api_router.include_router(upgrade_router, tags=["upgrade"])
