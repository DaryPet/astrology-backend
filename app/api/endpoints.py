from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from app.db.database import get_db
from app.models.models import User, NatalChart, ChartInterpretation, Book
from app.schemas.schemas import (
    UserCreate, UserResponse, NatalChartCreate, NatalChartResponse,
    InterpretationCreate, InterpretationResponse, BookCreate, BookResponse,
    QueryRequest, SynastryRequest
)
from app.utils.astrology import (
    calculate_planet_positions, calculate_aspects,
    calculate_solar_return, calculate_transits, calculate_synastry
)
import json

router = APIRouter()

# Users
@router.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    db_user = User(
        name=user.name,
        birth_date=user.birth_date,
        birth_time=user.birth_time,
        birth_place=user.birth_place,
        created_at=datetime.utcnow()
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# Natal Charts
@router.post("/charts", response_model=NatalChartResponse)
async def create_chart(chart: NatalChartCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == chart.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Calculate planetary positions
    positions = calculate_planet_positions(user.birth_date, user.birth_place)
    aspects = calculate_aspects(positions['planets'])
    
    db_chart = NatalChart(
        user_id=user.id,
        sun_sign=positions.get('sun_sign'),
        moon_sign=positions.get('moon_sign'),
        ascendant=positions.get('ascendant'),
        planets=json.dumps(positions['planets']),
        houses=json.dumps(positions.get('houses', {})),
        aspects=json.dumps(aspects),
        created_at=datetime.utcnow()
    )
    db.add(db_chart)
    await db.commit()
    await db.refresh(db_chart)
    return db_chart

@router.get("/charts/{chart_id}", response_model=NatalChartResponse)
async def get_chart(chart_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
    chart = result.scalar_one_or_none()
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")
    return chart

# Interpretations
@router.post("/charts/{chart_id}/interpret", response_model=InterpretationResponse)
async def interpret_chart(chart_id: int, interpretation: InterpretationCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
    chart = result.scalar_one_or_none()
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")
    
    # Generate interpretation using AI (simplified)
    planets = json.loads(chart.planets) if chart.planets else {}
    interpretation_text = f"Натальная карта {chart.sun_sign} солнечного знака. "
    interpretation_text += f"Луна в {chart.moon_sign}. Асцендент {chart.ascendant}. "
    interpretation_text += "Это базовая интерпретация. Для полной версии требуется AI."
    
    db_interp = ChartInterpretation(
        chart_id=chart_id,
        type=interpretation.type,
        interpretation=interpretation_text,
        created_at=datetime.utcnow()
    )
    db.add(db_interp)
    await db.commit()
    await db.refresh(db_interp)
    return db_interp

# Solar Return
@router.get("/charts/{chart_id}/solar-return")
async def get_solar_return(chart_id: int, year: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
    chart = result.scalar_one_or_none()
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")
    
    result = await db.execute(select(User).where(User.id == chart.user_id))
    user = result.scalar_one()
    
    solar = calculate_solar_return(user.birth_date, year)
    return solar

# Transits
@router.get("/charts/{chart_id}/transits")
async def get_transits(chart_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
    chart = result.scalar_one_or_none()
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")
    
    transits = calculate_transits(chart.created_at, datetime.utcnow())
    return transits

# Synastry
@router.post("/synastry")
async def create_synastry(request: SynastryRequest, db: AsyncSession = Depends(get_db)):
    result1 = await db.execute(select(NatalChart).where(NatalChart.id == request.chart1_id))
    chart1 = result1.scalar_one_or_none()
    if not chart1:
        raise HTTPException(status_code=404, detail="First chart not found")
    
    result2 = await db.execute(select(NatalChart).where(NatalChart.id == request.chart2_id))
    chart2 = result2.scalar_one_or_none()
    if not chart2:
        raise HTTPException(status_code=404, detail="Second chart not found")
    
    planets1 = json.loads(chart1.planets) if chart1.planets else {}
    planets2 = json.loads(chart2.planets) if chart2.planets else {}
    
    synastry = calculate_synastry(
        {'planets': planets1},
        {'planets': planets2}
    )
    return synastry

# Books
@router.post("/books", response_model=BookResponse)
async def create_book(book: BookCreate, db: AsyncSession = Depends(get_db)):
    db_book = Book(
        title=book.title,
        content=book.content,
        created_at=datetime.utcnow()
    )
    db.add(db_book)
    await db.commit()
    await db.refresh(db_book)
    return db_book

@router.get("/books")
async def get_books(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book))
    books = result.scalars().all()
    return books

@router.post("/books/{book_id}/query")
async def query_book(book_id: int, request: QueryRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Simple search (in production, use vector DB)
    content_lower = book.content.lower()
    query_lower = request.query.lower()
    
    if query_lower in content_lower:
        # Find context around the match
        idx = content_lower.find(query_lower)
        start = max(0, idx - 200)
        end = min(len(book.content), idx + len(request.query) + 200)
        context = book.content[start:end]
        return {"result": context, "book_title": book.title}
    
    return {"result": "No match found", "book_title": book.title}
