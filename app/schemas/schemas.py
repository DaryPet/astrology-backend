from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class UserCreate(BaseModel):
    name: str
    birth_date: datetime
    birth_time: Optional[str] = None
    birth_place: str

class UserResponse(UserCreate):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class PlanetPosition(BaseModel):
    planet: str
    sign: str
    degree: float
    house: Optional[int] = None

class NatalChartCreate(BaseModel):
    user_id: int

class NatalChartResponse(BaseModel):
    id: int
    user_id: int
    sun_sign: Optional[str] = None
    moon_sign: Optional[str] = None
    ascendant: Optional[str] = None
    planets: Optional[str] = None
    houses: Optional[str] = None
    aspects: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class InterpretationCreate(BaseModel):
    chart_id: int
    type: str  # "natal", "solar_return", "transit", "synastry"

class InterpretationResponse(BaseModel):
    id: int
    chart_id: int
    type: str
    interpretation: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class BookCreate(BaseModel):
    title: str
    content: str

class BookResponse(BookCreate):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class QueryRequest(BaseModel):
    query: str

class SynastryRequest(BaseModel):
    chart1_id: int
    chart2_id: int
