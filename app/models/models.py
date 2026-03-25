from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    name = Column(String, nullable=True)  # Опционально
    birth_date = Column(DateTime, nullable=True)  # Опционально - данные астрокарты
    birth_time = Column(String, nullable=True)  # Опционально - данные астрокарты
    birth_place = Column(String, nullable=True)  # Опционально - данные астрокарты
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    
    charts = relationship("NatalChart", back_populates="user")

class NatalChart(Base):
    __tablename__ = "natal_charts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    sun_sign = Column(String)
    moon_sign = Column(String)
    ascendant = Column(String)
    planets = Column(Text)  # JSON string
    houses = Column(Text)   # JSON string
    aspects = Column(Text)  # JSON string
    created_at = Column(DateTime, nullable=False)
    
    user = relationship("User", back_populates="charts")
    interpretations = relationship("ChartInterpretation", back_populates="chart")

class ChartInterpretation(Base):
    __tablename__ = "chart_interpretations"
    
    id = Column(Integer, primary_key=True, index=True)
    chart_id = Column(Integer, ForeignKey("natal_charts.id"))
    type = Column(String)  # "natal", "solar_return", "transit", "synastry"
    interpretation = Column(Text)
    created_at = Column(DateTime, nullable=False)
    
    chart = relationship("NatalChart", back_populates="interpretations")

class Book(Base):
    __tablename__ = "books"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
