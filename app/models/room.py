from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.db.session import Base

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    room_code = Column(String(20), unique=True, index=True, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    creator = relationship("User", back_populates="created_rooms", foreign_keys=[created_by_id])
    memberships = relationship("RoomMembership", back_populates="room", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="room", cascade="all, delete-orphan")
    settlements = relationship("Settlement", back_populates="room", cascade="all, delete-orphan")
