from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from jose import jwt
from app.core.config import settings

router = APIRouter()
security = HTTPBearer()

async def get_current_user(credentials = Depends(security)):
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated"
        )
        return {"id": payload.get("sub"), "email": payload.get("email")}
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.get("/me")
async def get_me(user = Depends(get_current_user)):
    return user