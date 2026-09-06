from datetime import datetime, timezone
import secrets
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.db.session import get_db
from app.models.room import Room
from app.models.membership import RoomMembership, MembershipStatus
from app.models.user import User
from app.schemas.room import (
    RoomCreate,
    RoomOut,
    RoomDetailOut,
    RoomInviteRequest,
    RoomInvitationOut,
    InvitationResponse,
    RoomMembershipOut,
)
from app.schemas.user import UserOut
from app.routers.deps import get_current_user

router = APIRouter(prefix="/rooms", tags=["rooms"])

@router.post("", response_model=RoomDetailOut, status_code=status.HTTP_201_CREATED)
def create_room(
    room_in: RoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    code = secrets.token_hex(4).upper()
    db_room = Room(
        name=room_in.name,
        description=room_in.description,
        room_code=code,
        created_by_id=current_user.id,
    )
    db.add(db_room)
    db.commit()
    db.refresh(db_room)

    # Automatically add creator as accepted member
    membership = RoomMembership(
        room_id=db_room.id,
        user_id=current_user.id,
        status=MembershipStatus.ACCEPTED.value,
        invited_by_id=current_user.id,
        responded_at=datetime.now(timezone.utc),
    )
    db.add(membership)
    db.commit()
    db.refresh(db_room)

    memberships_out = [
        RoomMembershipOut(
            id=membership.id,
            user_id=current_user.id,
            user=UserOut.model_validate(current_user),
            status=membership.status,
            created_at=membership.created_at,
            responded_at=membership.responded_at,
        )
    ]

    return RoomDetailOut(
        id=db_room.id,
        name=db_room.name,
        description=db_room.description,
        room_code=db_room.room_code,
        created_by_id=db_room.created_by_id,
        created_at=db_room.created_at,
        total_members=1,
        my_status=MembershipStatus.ACCEPTED.value,
        memberships=memberships_out,
    )

@router.get("", response_model=List[RoomOut])
def list_user_rooms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Rooms where the user is an accepted member
    memberships = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.user_id == current_user.id,
            RoomMembership.status == MembershipStatus.ACCEPTED.value,
        )
        .all()
    )
    results = []
    for m in memberships:
        r = m.room
        # Count accepted members
        active_count = (
            db.query(RoomMembership)
            .filter(
                RoomMembership.room_id == r.id,
                RoomMembership.status == MembershipStatus.ACCEPTED.value,
            )
            .count()
        )
        results.append(
            RoomOut(
                id=r.id,
                name=r.name,
                description=r.description,
                room_code=r.room_code,
                created_by_id=r.created_by_id,
                created_at=r.created_at,
                total_members=active_count,
                my_status=m.status,
            )
        )
    return results

@router.get("/invitations/pending", response_model=List[RoomInvitationOut])
def get_pending_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List pending invitations for the logged-in user to approve/decline."""
    pending = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.user_id == current_user.id,
            RoomMembership.status == MembershipStatus.PENDING.value,
        )
        .all()
    )
    results = []
    for m in pending:
        inviter = m.inviter or m.room.creator
        results.append(
            RoomInvitationOut(
                membership_id=m.id,
                room_id=m.room_id,
                room_name=m.room.name,
                room_description=m.room.description,
                invited_by=UserOut.model_validate(inviter),
                created_at=m.created_at,
            )
        )
    return results

@router.post("/invitations/{membership_id}/respond")
def respond_to_invitation(
    membership_id: int,
    resp: InvitationResponse,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve or decline an invitation to join a room."""
    membership = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.id == membership_id,
            RoomMembership.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found",
        )

    if membership.status != MembershipStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invitation already responded: {membership.status}",
        )

    action_upper = resp.action.strip().upper()
    if action_upper in ["ACCEPT", "APPROVE"]:
        membership.status = MembershipStatus.ACCEPTED.value
    elif action_upper in ["REJECT", "DECLINE"]:
        membership.status = MembershipStatus.REJECTED.value
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be ACCEPT or REJECT",
        )

    membership.responded_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "status": "success",
        "new_status": membership.status,
        "room_id": membership.room_id,
    }

@router.get("/{room_id}", response_model=RoomDetailOut)
def get_room_details(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify current user is a member (either pending or accepted)
    user_mem = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.room_id == room_id,
            RoomMembership.user_id == current_user.id,
        )
        .first()
    )
    if not user_mem:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this room",
        )

    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )

    memberships = (
        db.query(RoomMembership)
        .filter(RoomMembership.room_id == room_id)
        .all()
    )
    active_count = sum(1 for m in memberships if m.status == MembershipStatus.ACCEPTED.value)

    return RoomDetailOut(
        id=room.id,
        name=room.name,
        description=room.description,
        room_code=room.room_code,
        created_by_id=room.created_by_id,
        created_at=room.created_at,
        total_members=active_count,
        my_status=user_mem.status,
        memberships=[
            RoomMembershipOut(
                id=m.id,
                user_id=m.user.id,
                user=UserOut.model_validate(m.user),
                status=m.status,
                created_at=m.created_at,
                responded_at=m.responded_at,
            )
            for m in memberships
        ],
    )

@router.post("/{room_id}/invite", response_model=RoomMembershipOut)
def invite_user_to_room(
    room_id: int,
    req: RoomInviteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add/invite a roommate to the room. The invitee will receive notification and must approve."""
    # Verify sender is an active member
    sender_mem = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.room_id == room_id,
            RoomMembership.user_id == current_user.id,
            RoomMembership.status == MembershipStatus.ACCEPTED.value,
        )
        .first()
    )
    if not sender_mem:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only active room members can invite roommates",
        )

    # Find the target user by email or username
    query_str = req.username_or_email.strip()
    target_user = (
        db.query(User)
        .filter(or_(User.email == query_str, User.username == query_str))
        .first()
    )
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{query_str}' not found. Ask them to register first.",
        )

    # Check if already a member or invited
    existing_mem = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.room_id == room_id,
            RoomMembership.user_id == target_user.id,
        )
        .first()
    )
    if existing_mem:
        if existing_mem.status == MembershipStatus.ACCEPTED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{target_user.full_name} is already an active member of this room.",
            )
        elif existing_mem.status == MembershipStatus.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"An invitation for {target_user.full_name} is already pending approval.",
            )
        else:
            # Re-invite if previously rejected
            existing_mem.status = MembershipStatus.PENDING.value
            existing_mem.invited_by_id = current_user.id
            existing_mem.created_at = datetime.now(timezone.utc)
            existing_mem.responded_at = None
            db.commit()
            db.refresh(existing_mem)
            return RoomMembershipOut(
                id=existing_mem.id,
                user_id=target_user.id,
                user=UserOut.model_validate(target_user),
                status=existing_mem.status,
                created_at=existing_mem.created_at,
                responded_at=existing_mem.responded_at,
            )

    new_mem = RoomMembership(
        room_id=room_id,
        user_id=target_user.id,
        status=MembershipStatus.PENDING.value,
        invited_by_id=current_user.id,
    )
    db.add(new_mem)
    db.commit()
    db.refresh(new_mem)

    return RoomMembershipOut(
        id=new_mem.id,
        user_id=target_user.id,
        user=UserOut.model_validate(target_user),
        status=new_mem.status,
        created_at=new_mem.created_at,
        responded_at=new_mem.responded_at,
    )
