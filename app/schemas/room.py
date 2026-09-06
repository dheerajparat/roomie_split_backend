from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from app.schemas.user import UserOut

class RoomCreate(BaseModel):
    name: str
    description: Optional[str] = None

class RoomMembershipOut(BaseModel):
    id: int
    user_id: int
    user: UserOut
    status: str
    created_at: datetime
    responded_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class RoomOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    room_code: Optional[str]
    created_by_id: int
    created_at: datetime
    total_members: int = 0
    my_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class RoomDetailOut(RoomOut):
    memberships: List[RoomMembershipOut] = []

class RoomInviteRequest(BaseModel):
    username_or_email: str

class RoomInvitationOut(BaseModel):
    membership_id: int
    room_id: int
    room_name: str
    room_description: Optional[str]
    invited_by: UserOut
    created_at: datetime

class InvitationResponse(BaseModel):
    action: str  # "ACCEPT" or "REJECT"
