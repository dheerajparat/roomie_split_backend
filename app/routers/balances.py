from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.membership import RoomMembership, MembershipStatus
from app.models.settlement import Settlement
from app.models.user import User
from app.schemas.balance import (
    BalanceSummary,
    SettlementCreate,
    SettlementNotificationOut,
    SettlementOut,
    SettlementVerifyOut,
)
from app.schemas.user import UserOut
from app.services.calculation import compute_room_balances
from app.routers.deps import get_current_user

router = APIRouter(prefix="/rooms", tags=["balances"])

@router.get("/settlements/pending", response_model=List[SettlementNotificationOut])
def list_pending_settlement_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return settlement approvals waiting for the current receiver."""
    settlements = (
        db.query(Settlement)
        .filter(
            Settlement.receiver_id == current_user.id,
            Settlement.is_verified.is_(False),
        )
        .order_by(Settlement.settled_at.desc())
        .all()
    )

    return [
        SettlementNotificationOut(
            settlement_id=settlement.id,
            room_id=settlement.room_id,
            room_name=settlement.room.name,
            payer=UserOut.model_validate(settlement.payer),
            amount=settlement.amount,
            settled_at=settlement.settled_at,
            notes=settlement.notes,
        )
        for settlement in settlements
    ]

@router.get("/{room_id}/balances", response_model=BalanceSummary)
def get_balances(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Calculate and return net balances and simplified who-owes-whom suggestions."""
    # Verify user is an active member
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

    return compute_room_balances(db, room_id)

@router.post("/{room_id}/settle", response_model=SettlementOut, status_code=status.HTTP_201_CREATED)
def record_settlement(
    room_id: int,
    settle_in: SettlementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record a debt settlement payment from current user to receiver."""
    # Verify receiver exists and is in room
    rec_mem = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.room_id == room_id,
            RoomMembership.user_id == settle_in.receiver_id,
            RoomMembership.status == MembershipStatus.ACCEPTED.value,
        )
        .first()
    )
    if not rec_mem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Receiver is not an active member of this room",
        )

    settlement = Settlement(
        room_id=room_id,
        payer_id=current_user.id,
        receiver_id=settle_in.receiver_id,
        amount=round(settle_in.amount, 2),
        notes=settle_in.notes,
    )
    db.add(settlement)
    db.commit()
    db.refresh(settlement)

    return SettlementOut(
        id=settlement.id,
        room_id=settlement.room_id,
        payer_id=settlement.payer_id,
        payer=UserOut.model_validate(settlement.payer),
        receiver_id=settlement.receiver_id,
        receiver=UserOut.model_validate(settlement.receiver),
        amount=settlement.amount,
        settled_at=settlement.settled_at,
        notes=settlement.notes,
        is_verified=settlement.is_verified,
        verified_by_id=settlement.verified_by_id,
        verified_at=settlement.verified_at,
    )

@router.get("/{room_id}/settlements", response_model=List[SettlementOut])
def list_settlements(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all settlements for the room."""
    # Verify user is an active member
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

    settlements = (
        db.query(Settlement)
        .filter(Settlement.room_id == room_id)
        .order_by(Settlement.settled_at.desc())
        .all()
    )
    return [
        SettlementOut(
            id=s.id,
            room_id=s.room_id,
            payer_id=s.payer_id,
            payer=UserOut.model_validate(s.payer),
            receiver_id=s.receiver_id,
            receiver=UserOut.model_validate(s.receiver),
            amount=s.amount,
            settled_at=s.settled_at,
            notes=s.notes,
            is_verified=s.is_verified,
            verified_by_id=s.verified_by_id,
            verified_at=s.verified_at,
        )
        for s in settlements
    ]

@router.post(
    "/{room_id}/settlements/{settlement_id}/verify",
    response_model=SettlementVerifyOut,
)
def verify_settlement(
    room_id: int,
    settlement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Verify/confirm a settlement. Only the receiver of the settlement can verify it,
    confirming they actually received the money.
    """
    settlement = (
        db.query(Settlement)
        .filter(Settlement.id == settlement_id, Settlement.room_id == room_id)
        .first()
    )
    if not settlement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Settlement not found",
        )

    # Only the receiver can verify they received the money
    if settlement.receiver_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the receiver of the payment can verify this settlement",
        )

    if settlement.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Settlement is already verified",
        )

    settlement.is_verified = True
    settlement.verified_by_id = current_user.id
    settlement.verified_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(settlement)

    return SettlementVerifyOut(
        id=settlement.id,
        is_verified=settlement.is_verified,
        verified_by_id=settlement.verified_by_id,
        verified_at=settlement.verified_at,
    )
