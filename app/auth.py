from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
import httpx
from app.core.config import settings

router = APIRouter()
security = HTTPBearer()

async def get_current_user(credentials = Depends(security)):
    token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.SUPABASE_URL}/auth/v1/user",
                headers={
                    "apikey": settings.SUPABASE_KEY,
                    "Authorization": f"Bearer {token}"
                }
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            user_data = response.json()
            return {
                "id": user_data.get("id"),
                "email": user_data.get("email")
            }
    except httpx.HTTPError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.get("/me")
async def get_me(user = Depends(get_current_user)):
    return user