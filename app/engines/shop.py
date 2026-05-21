"""Shop redemption and refund logic."""

from app import db
from app.models import ShopItem, ShopPurchase
from app.engines import ledger


def redeem_item(quest_id, item_id, quest_campaign_id=None):
    """Attempt to redeem a shop item. Returns (success, message, purchase)."""
    item = db.session.get(ShopItem, item_id)
    if not item:
        return False, "Item not found", None

    if not item.is_available:
        return False, "Item is no longer available", None

    if item.quest_id and item.quest_id != quest_id:
        return False, "Item does not belong to this quest", None
    if item.campaign_id and item.campaign_id != quest_campaign_id:
        return False, "Item does not belong to this campaign", None

    if item.cost == 0:
        purchase = ShopPurchase(shop_item_id=item.id, quest_id=quest_id, transaction_id=None)
        db.session.add(purchase)
        db.session.commit()
        return True, f"Redeemed '{item.name}' (free)", purchase

    txn = ledger.record_spend(quest_id, item.cost, f"Purchased: {item.name}")
    if txn:
        db.session.flush()
        purchase = ShopPurchase(shop_item_id=item.id, quest_id=quest_id, transaction_id=txn.id)
        db.session.add(purchase)
        db.session.commit()
        return True, f"Redeemed '{item.name}'", purchase

    return False, f"Insufficient balance for '{item.name}'", None
