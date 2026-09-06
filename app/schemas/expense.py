from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.user import UserOut

class ExpenseSplitOut(BaseModel):
    id: int
    user_id: int
    user: UserOut
    share_amount: float

    model_config = ConfigDict(from_attributes=True)

class ExpenseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Item or expense title")
    description: Optional[str] = None
    amount: float = Field(..., gt=0, description="Expense cost in currency")
    category: str = Field(default="Groceries", description="Category (e.g. Groceries, Food, Utilities, Rent, Household)")
    expense_date: Optional[date] = Field(default=None, description="Date when item was brought/spent")
    paid_by_id: Optional[int] = Field(default=None, description="User who paid. Defaults to current user if omitted")
    split_user_ids: Optional[List[int]] = Field(default=None, description="Roommates sharing this expense. Defaults to all active members if omitted")

class ExpenseOut(BaseModel):
    id: int
    room_id: int
    title: str
    description: Optional[str]
    amount: float
    category: str
    expense_date: date
    paid_by_id: int
    paid_by: UserOut
    created_at: datetime
    splits: List[ExpenseSplitOut] = []

    model_config = ConfigDict(from_attributes=True)
