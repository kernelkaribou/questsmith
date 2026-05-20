"""Party goal progress calculation — shared between quest and campaign views."""
import math

from app import db
from app.models import Quest, PartyGoal
from app.engines import ledger


def get_member_goal_progress(campaign_id, member_id):
    """Calculate party goal progress for a specific member's quest view."""
    party_goals = PartyGoal.query.filter_by(campaign_id=campaign_id).order_by(PartyGoal.sort_order).all()
    if not party_goals:
        return []

    campaign_totals = ledger.get_campaign_totals(campaign_id)
    my_contribution = campaign_totals.get(member_id, 0)
    num_members = db.session.query(Quest.member_id).filter_by(campaign_id=campaign_id).distinct().count()

    goal_progress = []
    for goal in party_goals:
        target = goal.target_amount or 1
        min_req = math.ceil(target / num_members) if num_members > 0 else target
        capped_total = sum(min(v, min_req) for v in campaign_totals.values())
        all_met_min = all(
            campaign_totals.get(mid, 0) >= min_req
            for mid, in db.session.query(Quest.member_id).filter_by(campaign_id=campaign_id).distinct()
        )
        complete = capped_total >= target and all_met_min
        goal_progress.append({
            "goal": goal,
            "current": capped_total,
            "my_contribution": min(my_contribution, min_req),
            "my_percent": min(100, int(my_contribution / min_req * 100)) if min_req > 0 else 100,
            "percent": min(100, int(capped_total / target * 100)),
            "my_remaining": max(0, min_req - my_contribution),
            "min_required": min_req,
            "min_marker_percent": min(100, int(min_req / target * 100)) if min_req else 0,
            "all_met_min": all_met_min,
            "complete": complete,
        })

    active_found = False
    for g in goal_progress:
        if g["complete"]:
            g["visible"] = True
        elif not active_found:
            g["visible"] = True
            active_found = True
        else:
            g["visible"] = False

    return goal_progress
