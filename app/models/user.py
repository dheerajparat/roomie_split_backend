from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from app.db.session import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    created_rooms = relationship("Room", back_populates="creator", foreign_keys="Room.created_by_id")
    memberships = relationship("RoomMembership", back_populates="user", foreign_keys="RoomMembership.user_id")
    paid_expenses = relationship("Expense", back_populates="payer", foreign_keys="Expense.paid_by_id")
    splits = relationship("ExpenseSplit", back_populates="user", foreign_keys="ExpenseSplit.user_id")
