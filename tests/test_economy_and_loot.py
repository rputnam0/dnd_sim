from __future__ import annotations

import pytest

from dnd_sim.economy import (
    MarketItem,
    create_economy_state,
    generate_loot_drop,
    generate_vendor_inventory,
    price_item,
    purchase_from_vendor,
)
from dnd_sim.inventory import CurrencyWallet
from dnd_sim.snapshot_codecs import deserialize_economy_state, serialize_economy_state


def _catalog() -> dict[str, MarketItem]:
    return {
        "hempen_rope": MarketItem(
            item_id="hempen_rope",
            name="Hempen Rope",
            base_price_cp=100,
            vendor_weight=3,
            loot_weight=1,
            min_vendor_quantity=2,
            max_vendor_quantity=2,
        ),
        "rations": MarketItem(
            item_id="rations",
            name="Rations",
            base_price_cp=50,
            vendor_weight=2,
            loot_weight=3,
            min_vendor_quantity=4,
            max_vendor_quantity=4,
        ),
        "healing_potion": MarketItem(
            item_id="healing_potion",
            name="Potion of Healing",
            base_price_cp=500,
            rarity="uncommon",
            vendor_weight=1,
            loot_weight=2,
            min_vendor_quantity=1,
            max_vendor_quantity=1,
        ),
    }


def test_price_item_applies_market_markup_and_discount_deterministically() -> None:
    item = MarketItem(
        item_id="longsword",
        name="Longsword",
        base_price_cp=1500,
    )

    price = price_item(
        item,
        market_price_index_bp=11_000,
        vendor_markup_bp=12_000,
        discount_bp=500,
    )

    assert price == 1_881


def test_generate_vendor_inventory_is_seed_stable_and_uses_price_model() -> None:
    catalog = _catalog()

    first = generate_vendor_inventory(
        vendor_id="dock_merchant",
        catalog=catalog,
        seed=17,
        stock_count=2,
        market_price_index_bp=10_500,
        markup_bp=11_500,
    )
    second = generate_vendor_inventory(
        vendor_id="dock_merchant",
        catalog=catalog,
        seed=17,
        stock_count=2,
        market_price_index_bp=10_500,
        markup_bp=11_500,
    )

    assert first == second
    assert len(first.stock) == 2
    for stock in first.stock.values():
        assert stock.unit_price_cp == price_item(
            catalog[stock.item_id],
            market_price_index_bp=10_500,
            vendor_markup_bp=11_500,
        )


def test_generate_loot_drop_is_seed_stable_and_spends_within_budget() -> None:
    catalog = _catalog()

    first = generate_loot_drop(
        catalog=catalog,
        seed=29,
        budget_cp=900,
        max_items=4,
        currency_share_bp=2_500,
    )
    second = generate_loot_drop(
        catalog=catalog,
        seed=29,
        budget_cp=900,
        max_items=4,
        currency_share_bp=2_500,
    )

    assert first == second
    items_total = sum(
        catalog[item_id].base_price_cp * quantity
        for item_id, quantity in first.item_quantities.items()
    )
    assert items_total + first.currency_cp == 900
    assert sum(first.item_quantities.values()) <= 4
    assert first.currency_cp >= 225


def test_purchase_from_vendor_spends_currency_and_reduces_stock() -> None:
    state = create_economy_state(
        catalog=_catalog(),
        vendors={
            "dock_merchant": {
                "markup_bp": 11_000,
                "stock": {
                    "hempen_rope": {
                        "quantity": 3,
                        "unit_price_cp": 120,
                    }
                },
            }
        },
    )
    wallet = CurrencyWallet(gp=5)

    next_state, total_cost_cp = purchase_from_vendor(
        state,
        vendor_id="dock_merchant",
        item_id="hempen_rope",
        quantity=2,
        buyer_wallet=wallet,
    )

    assert total_cost_cp == 240
    assert wallet.total_cp == 260
    assert next_state.vendors["dock_merchant"].stock["hempen_rope"].quantity == 1
    assert state.vendors["dock_merchant"].stock["hempen_rope"].quantity == 3


def test_purchase_from_vendor_rejects_illegal_requests() -> None:
    state = create_economy_state(
        catalog=_catalog(),
        vendors={
            "dock_merchant": {
                "stock": {
                    "hempen_rope": {
                        "quantity": 1,
                        "unit_price_cp": 120,
                    }
                }
            }
        },
    )

    with pytest.raises(KeyError, match="Unknown vendor_id=missing_vendor"):
        purchase_from_vendor(
            state,
            vendor_id="missing_vendor",
            item_id="hempen_rope",
            quantity=1,
            buyer_wallet=CurrencyWallet(gp=10),
        )

    with pytest.raises(ValueError, match="quantity exceeds vendor stock"):
        purchase_from_vendor(
            state,
            vendor_id="dock_merchant",
            item_id="hempen_rope",
            quantity=2,
            buyer_wallet=CurrencyWallet(gp=10),
        )

    with pytest.raises(ValueError, match="Insufficient currency"):
        purchase_from_vendor(
            state,
            vendor_id="dock_merchant",
            item_id="hempen_rope",
            quantity=1,
            buyer_wallet=CurrencyWallet(cp=50),
        )


def test_economy_state_round_trips_through_persistence_payload() -> None:
    catalog = _catalog()
    vendor = generate_vendor_inventory(
        vendor_id="dock_merchant",
        catalog=catalog,
        seed=7,
        stock_count=3,
    )
    state = create_economy_state(
        day_index=5,
        market_price_index_bp=10_300,
        catalog=catalog,
        vendors={"dock_merchant": vendor},
    )

    payload = serialize_economy_state(state)
    restored = deserialize_economy_state(payload)

    assert restored == state
