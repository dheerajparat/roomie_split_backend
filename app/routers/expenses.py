from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.room import Room
from app.models.membership import RoomMembership, MembershipStatus
from app.models.expense import Expense, ExpenseSplit
from app.models.user import User
from app.schemas.expense import ExpenseCreate, ExpenseOut, ExpenseSplitOut
from app.schemas.user import UserOut
from app.routers.deps import get_current_user

router = APIRouter(prefix="/rooms", tags=["expenses"])

@router.post("/{room_id}/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(
    room_id: int,
    expense_in: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify current user is an active member
    mem = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.room_id == room_id,
            RoomMembership.user_id == current_user.id,
            RoomMembership.status == MembershipStatus.ACCEPTED.value,
        )
        .first()
    )
    if not mem:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only active members of this room can add expenses",
        )

    # Get all active members for splitting
    active_memberships = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.room_id == room_id,
            RoomMembership.status == MembershipStatus.ACCEPTED.value,
        )
        .all()
    )
    active_member_ids = {m.user_id for m in active_memberships}

    # Determine payer
    payer_id = expense_in.paid_by_id if expense_in.paid_by_id is not None else current_user.id
    if payer_id not in active_member_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payer (user_id={payer_id}) is not an active member of this room",
        )

    # Determine split members (default to all active room members if not specified)
    if expense_in.split_user_ids and len(expense_in.split_user_ids) > 0:
        split_ids = list(set(expense_in.split_user_ids))
        for uid in split_ids:
            if uid not in active_member_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Split user (user_id={uid}) is not an active member of this room",
                )
    else:
        # Default: all active members in the room
        split_ids = list(active_member_ids)

    if not split_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one active member must be included in the split",
        )

    # Determine expense date
    exp_date = expense_in.expense_date or datetime.now(timezone.utc).date()

    # Create expense
    db_expense = Expense(
        room_id=room_id,
        title=expense_in.title.strip(),
        description=expense_in.description,
        amount=round(expense_in.amount, 2),
        category=expense_in.category or "Groceries",
        expense_date=exp_date,
        paid_by_id=payer_id,
    )
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)

    # Calculate equal share among selected members
    num_participants = len(split_ids)
    base_share = round(db_expense.amount / num_participants, 2)
    # Handle penny rounding
    rounding_diff = round(db_expense.amount - (base_share * num_participants), 2)

    for i, uid in enumerate(split_ids):
        # Adjust penny diff on first participant
        share = base_share + (rounding_diff if i == 0 else 0.0)
        split = ExpenseSplit(
            expense_id=db_expense.id,
            user_id=uid,
            share_amount=round(share, 2),
        )
        db.add(split)

    db.commit()
    db.refresh(db_expense)

    splits_out = [
        ExpenseSplitOut(
            id=s.id,
            user_id=s.user_id,
            user=UserOut.model_validate(s.user),
            share_amount=s.share_amount,
        )
        for s in db_expense.splits
    ]

    return ExpenseOut(
        id=db_expense.id,
        room_id=db_expense.room_id,
        title=db_expense.title,
        description=db_expense.description,
        amount=db_expense.amount,
        category=db_expense.category,
        expense_date=db_expense.expense_date,
        paid_by_id=db_expense.paid_by_id,
        paid_by=UserOut.model_validate(db_expense.payer),
        created_at=db_expense.created_at,
        splits=splits_out,
    )

@router.get("/{room_id}/expenses", response_model=List[ExpenseOut])
def list_expenses(
    room_id: int,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify current user is a member
    mem = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.room_id == room_id,
            RoomMembership.user_id == current_user.id,
            RoomMembership.status == MembershipStatus.ACCEPTED.value,
        )
        .first()
    )
    if not mem:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this room",
        )

    query = db.query(Expense).filter(Expense.room_id == room_id)
    if category:
        query = query.filter(Expense.category == category)

    expenses = query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).all()

    results = []
    for exp in expenses:
        splits_out = [
            ExpenseSplitOut(
                id=s.id,
                user_id=s.user_id,
                user=UserOut.model_validate(s.user),
                share_amount=s.share_amount,
            )
            for s in exp.splits
        ]
        results.append(
            ExpenseOut(
                id=exp.id,
                room_id=exp.room_id,
                title=exp.title,
                description=exp.description,
                amount=exp.amount,
                category=exp.category,
                expense_date=exp.expense_date,
                paid_by_id=exp.paid_by_id,
                paid_by=UserOut.model_validate(exp.payer),
                created_at=exp.created_at,
                splits=splits_out,
            )
        )
    return results

@router.delete("/{room_id}/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    room_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    exp = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.room_id == room_id)
        .first()
    )
    if not exp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found",
        )

    # Allow payer or room creator to delete
    room = db.query(Room).filter(Room.id == room_id).first()
    if exp.paid_by_id != current_user.id and (room and room.created_by_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this expense",
        )

    db.delete(exp)
    db.commit()
    return None
