from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.user import UserOut

class MemberBalance(BaseModel):
    user_id: int
    user: UserOut
    total_paid: float
    total_share: float
    net_balance: float  # Positive: is owed money; Negative: owes money

class DebtTransaction(BaseModel):
    from_user: UserOut
    to_user: UserOut
    amount: float

class BalanceSummary(BaseModel):
    room_id: int
    total_room_expenses: float
    member_balances: List[MemberBalance]
    suggested_settlements: List[DebtTransaction]

class SettlementCreate(BaseModel):
    receiver_id: int
    amount: float = Field(..., gt=0)
    notes: Optional[str] = None

class SettlementOut(BaseModel):
    id: int
    room_id: int
    payer_id: int
    payer: UserOut
    receiver_id: int
    receiver: UserOut
    amount: float
    settled_at: datetime
    notes: Optional[str]

    model_config = ConfigDict(from_attributes=True)
