"""Parser tests against sanitized HTML fixtures captured from telepizza.es.

No tocan la red: monkeypatchean los métodos de fetch del cliente. Si Telepizza
cambia el frontal, recaptura las fixtures (ver tests/fixtures/) y ajusta los
parsers.
"""

from pathlib import Path

import pytest

from telepizza_mcp.client import TelepizzaClient

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


@pytest.fixture
def client(monkeypatch):
    c = TelepizzaClient("user@example.com", "secret")
    c.logged_in = True
    c.store = {"shopId": "00000"}  # evita ensure_store en parsers
    return c


def test_parse_menu_products(client):
    products = client._parse_products(fixture("menu_tiles.html"))
    assert len(products) == 3
    first = products[0]
    assert first["id"]
    assert first["name"]
    assert first["price_eur"] not in (None, "0.00")
    assert first["url"].startswith("https://www.telepizza.es/product/")


def test_parse_offers(client, monkeypatch):
    monkeypatch.setattr(
        client, "_get", lambda path, **kw: FakeResponse(fixture("offer_tiles.html"))
    )
    offers = client._fetch_offers()
    assert len(offers) == 3
    assert all(o["id"] for o in offers)
    assert offers[0]["name"]
    assert offers[0]["description"]


def test_parse_order_history(client, monkeypatch):
    monkeypatch.setattr(
        client, "_authed_html", lambda path, **kw: fixture("order_history_cards.html")
    )
    orders = client.order_history()
    assert len(orders) == 2
    assert orders[0]["order_id"] == "10000001"
    assert orders[0]["date"]
    assert orders[0]["items"][0]["product"]


def test_parse_loyalty_status(client, monkeypatch):
    monkeypatch.setattr(
        client, "_authed_html", lambda path, **kw: fixture("loyalty_activity.html")
    )
    st = client.loyalty_status()
    assert st["summary"]["points_disponibles"] == 9410
    assert st["summary"]["points_pendientes"] == 1295
    assert st["movements"]
    assert st["movements"][0]["date"].count("/") == 2


def test_parse_loyalty_rewards(client, monkeypatch):
    monkeypatch.setattr(
        client, "_authed_html", lambda path, **kw: fixture("loyalty_rewards.html")
    )
    rewards = client.loyalty_rewards()
    assert len(rewards) == 3
    assert rewards[0]["id"].startswith("LY")
    assert rewards[0]["points"] > 0
    assert rewards[0]["channel"] in ("delivery", "takeaway")


def test_parse_empty_cart(client, monkeypatch):
    monkeypatch.setattr(
        client, "_get", lambda path, **kw: FakeResponse(fixture("minicart_empty.html"))
    )
    cart = client.cart()
    assert cart["empty"] is True
    assert cart["items"] == []
    assert cart["total"] == "0,00€"


def test_parse_product_details(client, monkeypatch):
    monkeypatch.setattr(
        client, "_get", lambda path, **kw: FakeResponse(fixture("quickview.html"))
    )
    details = client.product_details("999990013693121")
    assert {s["label"] for s in details["sizes"]} == {"Mediana"}
    assert details["option_groups"]
    ids = [g["id"] for g in details["option_groups"] if g["id"]]
    assert "tpz_productBases" in ids


def test_parse_store_options_from_getstore(client, monkeypatch):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fixture("getstore_rendered.html"), "html.parser")
    opts = soup.select("select[name=deliveryHour] option")
    assert opts, "fixture must contain the deliveryHour select"
    first = opts[0]
    assert first["data-store-id"]
    assert first["value"].startswith("20")  # ISO datetime


def test_looks_logged_out():
    assert TelepizzaClient._looks_logged_out('<input id="login-form-email">') is True
    assert (
        TelepizzaClient._looks_logged_out(
            '<a>Cerrar sesión</a><input id="login-form-email">'
        )
        is False
    )
