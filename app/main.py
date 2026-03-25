from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from app.api.public import router as public_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.db.database import init_db
from app.core.config import settings
import os
import mimetypes

# Add missing MIME types
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')

app = FastAPI(title="Astrology API", description="Fullstack Astrology Application")

# CORS - must be before static files
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers BEFORE static files
# Публичные API (не требуют аутентификации)
app.include_router(public_router, prefix="/api")

# API аутентификации (без дополнительного префикса, так как уже есть в роутере)
app.include_router(auth_router, prefix="/api")

# Защищенные API (требуют аутентификации)
app.include_router(dashboard_router, prefix="/api")

# Serve static files from frontend build - AFTER API routes
static_dir = os.path.join(os.path.dirname(__file__), "../../frontend/dist")

# Use StaticFiles for proper static file serving
if os.path.exists(static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")

# Serve index.html for root - AFTER static files
@app.get("/")
async def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Astrology API"}

# Catch-all for SPA routes - MUST be LAST
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
