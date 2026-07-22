"""MCP server exposing read-only telepizza.es tools.

Credenciales vía variables de entorno TELEPIZZA_EMAIL / TELEPIZZA_PASSWORD
(cargadas de .env si existe). Servidor stdio para Claude Code / Desktop.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .client import MENU_CATEGORIES, TelepizzaClient

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()  # también un .env del cwd, si existe

mcp = FastMCP("telepizza")

_client: TelepizzaClient | None = None


def client() -> TelepizzaClient:
    global _client
    if _client is None:
        email = os.environ.get("TELEPIZZA_EMAIL")
        password = os.environ.get("TELEPIZZA_PASSWORD")
        if not email or not password:
            raise RuntimeError(
                "Set TELEPIZZA_EMAIL and TELEPIZZA_PASSWORD (e.g. in .env)"
            )
        _client = TelepizzaClient(email, password)
    return _client


@mcp.tool()
def login() -> dict[str, Any]:
    """Log in to telepizza.es with the configured account and report session state."""
    c = client()
    data = c.login()
    return {
        "logged_in": True,
        "email": c.email,
        "loyalty_contact_id": data.get("loyaltyContactId"),
    }


@mcp.tool()
def list_saved_addresses() -> list[dict[str, Any]]:
    """List the delivery addresses saved in the Telepizza account."""
    return client().saved_addresses()


@mcp.tool()
def set_delivery_address(address_id: str = "") -> dict[str, Any]:
    """Bind the session to the delivery store for a saved address.

    Required before menu prices are available. With no address_id, uses the
    account's default (selected) saved address. Returns the assigned store,
    minimum order amount, delivery cost and available delivery slots.
    """
    c = client()
    address = None
    if address_id:
        matches = [a for a in c.saved_addresses() if a.get("ID") == address_id]
        if not matches:
            raise ValueError(f"No saved address with ID {address_id}")
        address = matches[0]
    return c.set_delivery_address(address)


@mcp.tool()
def find_stores(address: str) -> list[dict[str, Any]]:
    """Find Telepizza delivery stores near a free-form Spanish address.

    The address is geocoded with Nominatim (OpenStreetMap) first, so include
    street, number and city, e.g. "Calle Mayor 1, Madrid".
    """
    return client().find_stores(address)


@mcp.tool()
def get_menu(category: str = "pizzas") -> list[dict[str, Any]]:
    """Get menu products with prices for the session's store.

    Categories: ofertas, pizzas, entrantes, burgers, postres, bebidas.
    Also accepts a raw site path like "/comida-a-domicilio/pizzas/las-clasicas".
    Prices require a delivery address (set_delivery_address is called
    automatically with the default saved address if needed).
    """
    if category not in MENU_CATEGORIES and not category.startswith("/"):
        raise ValueError(
            f"Unknown category {category!r}; use one of {sorted(MENU_CATEGORIES)} or a site path"
        )
    return client().menu(category)


@mcp.tool()
def get_offers() -> list[dict[str, Any]]:
    """Get current offers/promotions with prices for the session's store."""
    return client().offers()


@mcp.tool()
def get_product_details(product_id: str) -> dict[str, Any]:
    """Get sizes, dough/sauce/ingredient options and price of one product.

    Use the product ids returned by get_menu or search_products. Price may be
    null when the delivery store is closed.
    """
    return client().product_details(product_id)


@mcp.tool()
def get_offer_details(offer_id: str) -> dict[str, Any]:
    """Get the full conditions of one promotion (ids from get_offers).

    Availability depends on the session store; with the store closed the site
    reports the promotion as unavailable.
    """
    return client().offer_details(offer_id)


@mcp.tool()
def search_products(query: str) -> list[dict[str, Any]]:
    """Full-text search of products across the whole menu."""
    return client().search_products(query)


@mcp.tool()
def get_store_schedule(address: str) -> list[dict[str, Any]]:
    """Weekly delivery schedule of the Telepizza stores near an address."""
    return client().store_schedule(address)


@mcp.tool()
def get_delivery_slots() -> dict[str, Any]:
    """Available delivery time slots today for the default saved address.

    Fails with the site's message when the store is closed.
    """
    return client().delivery_slots()


@mcp.tool()
def get_loyalty_status() -> dict[str, Any]:
    """MiTelepi loyalty points: available, pending, redeemed and last movements."""
    return client().loyalty_status()


@mcp.tool()
def get_cart() -> dict[str, Any]:
    """Read-only snapshot of the current cart (items, total, delivery address)."""
    return client().cart()


@mcp.tool()
def status() -> dict[str, Any]:
    """Session, store and opening status: logged in, default address, whether
    the delivery store is open now, next slot and today's hours. Call this
    first when other tools fail or return no prices."""
    return client().status()


@mcp.tool()
def get_loyalty_rewards() -> list[dict[str, Any]]:
    """MiTelepi rewards catalog: what your points buy (title, description,
    points cost, price and channel delivery/takeaway).

    Redemption happens when ordering: the reward appears as a promotion in
    the cart/offers flow once you have enough points; this MCP does not
    place orders, so redeeming is completed on the website or app.
    """
    return client().loyalty_rewards()


@mcp.tool()
def add_to_cart(product_id: str, quantity: int = 1) -> dict[str, Any]:
    """WRITE — adds a product to the real cart of the account (no payment).

    For sized products use the variant pid "<id>-<talla>", e.g.
    "999990000006814-mediana" (tallas: individual, mediana, familiar).
    """
    return client().add_to_cart(product_id, quantity)


@mcp.tool()
def reorder(order_id: str) -> dict[str, Any]:
    """WRITE — fills the real cart with the items of a previous order
    (ids from get_order_history). Does not pay or place any order."""
    return client().reorder(order_id)


@mcp.tool()
def remove_from_cart(remove_url: str) -> dict[str, Any]:
    """WRITE — removes one cart line. Pass the remove_url that get_cart
    reports for the item."""
    return client().remove_from_cart(remove_url)


@mcp.tool()
def clear_cart() -> dict[str, Any]:
    """WRITE — empties the cart completely. Returns the final snapshot."""
    return client().clear_cart()


@mcp.tool()
def toggle_favorite_order(order_id: str) -> dict[str, Any]:
    """WRITE — marks/unmarks a past order as favorite in the account."""
    return client().toggle_favorite_order(order_id)


@mcp.tool()
def get_order_history() -> list[dict[str, Any]]:
    """List past orders of the account (order id, date and items)."""
    return client().order_history()


@mcp.tool()
def get_order_details(order_id: str) -> dict[str, Any]:
    """Get details of one order: date, shipping method, payment and totals."""
    return client().order_details(order_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
