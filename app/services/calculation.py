from typing import List, Dict
from sqlalchemy.orm import Session
from app.models.room import Room
from app.models.membership import RoomMembership, MembershipStatus
from app.models.expense import Expense, ExpenseSplit
from app.models.settlement import Settlement
from app.models.user import User
from app.schemas.user import UserOut
from app.schemas.balance import MemberBalance, DebtTransaction, BalanceSummary

def compute_room_balances(db: Session, room_id: int) -> BalanceSummary:
    # 1. Fetch active members
    memberships = (
        db.query(RoomMembership)
        .filter(
            RoomMembership.room_id == room_id,
            RoomMembership.status == MembershipStatus.ACCEPTED.value
        )
        .all()
    )
    active_users: Dict[int, User] = {m.user.id: m.user for m in memberships}

    # If creator is not in memberships for some reason, ensure creator is included
    room = db.query(Room).filter(Room.id == room_id).first()
    if room and room.creator.id not in active_users:
        active_users[room.creator.id] = room.creator

    # Initialize accounting dicts
    paid_amounts: Dict[int, float] = {u_id: 0.0 for u_id in active_users}
    share_amounts: Dict[int, float] = {u_id: 0.0 for u_id in active_users}
    settlement_adjustments: Dict[int, float] = {u_id: 0.0 for u_id in active_users}

    # 2. Fetch all expenses
    expenses = db.query(Expense).filter(Expense.room_id == room_id).all()
    total_room_expenses = sum(e.amount for e in expenses)

    for exp in expenses:
        if exp.paid_by_id in paid_amounts:
            paid_amounts[exp.paid_by_id] += exp.amount
        else:
            paid_amounts[exp.paid_by_id] = exp.amount
            if exp.payer:
                active_users[exp.paid_by_id] = exp.payer

        for split in exp.splits:
            if split.user_id in share_amounts:
                share_amounts[split.user_id] += split.share_amount
            else:
                share_amounts[split.user_id] = split.share_amount
                if split.user:
                    active_users[split.user_id] = split.user

    # 3. Fetch all settlements
    settlements = db.query(Settlement).filter(Settlement.room_id == room_id).all()
    for s in settlements:
        # Payer paid off debt -> increases their net standing
        settlement_adjustments[s.payer_id] = settlement_adjustments.get(s.payer_id, 0.0) + s.amount
        # Receiver received payment -> decreases their claim
        settlement_adjustments[s.receiver_id] = settlement_adjustments.get(s.receiver_id, 0.0) - s.amount

    # 4. Compute Net Balances
    member_balances: List[MemberBalance] = []
    # Dict for debt simplification algorithm: {user_id: net_balance}
    net_map: Dict[int, float] = {}

    for u_id, user in active_users.items():
        paid = round(paid_amounts.get(u_id, 0.0), 2)
        share = round(share_amounts.get(u_id, 0.0), 2)
        adj = round(settlement_adjustments.get(u_id, 0.0), 2)
        net = round(paid - share + adj, 2)
        net_map[u_id] = net

        member_balances.append(
            MemberBalance(
                user_id=u_id,
                user=UserOut.model_validate(user),
                total_paid=paid,
                total_share=share,
                net_balance=net,
            )
        )

    # 5. Greedy Debt Simplification
    # Debtors have net < -0.01 (owe money)
    # Creditors have net > 0.01 (are owed money)
    debtors = []
    creditors = []

    for u_id, net in net_map.items():
        if net < -0.01:
            debtors.append({"user_id": u_id, "amount": -net})
        elif net > 0.01:
            creditors.append({"user_id": u_id, "amount": net})

    debtors.sort(key=lambda x: x["amount"], reverse=True)
    creditors.sort(key=lambda x: x["amount"], reverse=True)

    suggested_settlements: List[DebtTransaction] = []
    d_idx = 0
    c_idx = 0

    while d_idx < len(debtors) and c_idx < len(creditors):
        debtor = debtors[d_idx]
        creditor = creditors[c_idx]

        settle_amt = min(debtor["amount"], creditor["amount"])
        if settle_amt > 0.01:
            suggested_settlements.append(
                DebtTransaction(
                    from_user=UserOut.model_validate(active_users[debtor["user_id"]]),
                    to_user=UserOut.model_validate(active_users[creditor["user_id"]]),
                    amount=round(settle_amt, 2),
                )
            )

        debtor["amount"] -= settle_amt
        creditor["amount"] -= settle_amt

        if debtor["amount"] < 0.01:
            d_idx += 1
        if creditor["amount"] < 0.01:
            c_idx += 1

    return BalanceSummary(
        room_id=room_id,
        total_room_expenses=round(total_room_expenses, 2),
        member_balances=member_balances,
        suggested_settlements=suggested_settlements,
    )
