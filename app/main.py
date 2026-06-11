from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse
from app.api.endpoints import router as api_router
# from app.auth_routes_simple import router as auth_router
# from app.db.database import init_db, engine
from app.db.database import engine 
from app.auth import router as supabase_auth_router
# from app.auth_models import AuthBase
import os
import mimetypes

# Add missing MIME types
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')

app = FastAPI(title="Astrology API", description="Fullstack Astrology Application")

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please slow down."})

# CORS - must be before static files
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers BEFORE static files
app.include_router(api_router, prefix="/api")
app.include_router(supabase_auth_router, prefix="/api/auth")

# Include authentication router (без префикса, так как он уже встроен в пути)
# app.include_router(auth_router)

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
