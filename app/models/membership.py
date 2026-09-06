from datetime import datetime, timezone
import enum
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from app.db.session import Base

class MembershipStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"

class RoomMembership(Base):
    __tablename__ = "room_memberships"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), default=MembershipStatus.PENDING.value, nullable=False)
    invited_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    responded_at = Column(DateTime, nullable=True)

    # Relationships
    room = relationship("Room", back_populates="memberships")
    user = relationship("User", back_populates="memberships", foreign_keys=[user_id])
    inviter = relationship("User", foreign_keys=[invited_by_id])
