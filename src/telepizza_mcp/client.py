"""HTTP client for telepizza.es (Salesforce Commerce Cloud / Demandware storefront).

telepizza.es no tiene API pública; este cliente replica las llamadas que hace
la propia web contra sus controladores Demandware:
  https://www.telepizza.es/on/demandware.store/Sites-TelepizzaES-Site/default/<Controller>-<Action>

Solo operaciones de consulta: login, tiendas, carta, ofertas e historial de
pedidos. Nada de carrito ni checkout.

Flujo descubierto por ingeniería inversa de la web (2026-07):
- Login: POST form-encoded a Account-Login con csrf_token de la home.
  Cuentas "migradas" antiguas: el servidor devuelve un salt bcrypt y se
  reenvía el hash a Account-LoginMigratedCustomer.
- Precios: solo aparecen con tienda en sesión. Secuencia:
  Stores-GetStore?lat&lng&method=delivery -> renderedHtml con <select
  name=deliveryHour> cuyas <option> llevan data-store-* -> POST JSON a
  Stores-SetStore (¡body JSON, no form!; con form devuelve 410).
- Direcciones guardadas: embebidas en la home logueada como JSON en los
  botones data-select-address.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.telepizza.es"
CONTROLLER = "/on/demandware.store/Sites-TelepizzaES-Site/default/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

MENU_CATEGORIES = {
    "ofertas": "/ofertas",
    "pizzas": "/comida-a-domicilio/pizzas",
    "entrantes": "/comida-a-domicilio/entrantes",
    "burgers": "/comida-a-domicilio/burgersymas",
    "postres": "/comida-a-domicilio/postres",
    "bebidas": "/comida-a-domicilio/bebidas",
}


class TelepizzaError(Exception):
    pass


class TelepizzaClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.logged_in = False
        self.store: dict[str, Any] | None = None
        self.http = httpx.Client(
            base_url=BASE,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "es-ES,es;q=0.9",
            },
            follow_redirects=True,
            timeout=30,
        )

    # ------------------------------------------------------------------ utils

    def _get(self, path: str, **kw) -> httpx.Response:
        r = self.http.get(path, **kw)
        r.raise_for_status()
        return r

    def _csrf(self, html: str | None = None) -> str:
        html = html or self._get("/").text
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        if not m:
            raise TelepizzaError("No CSRF token found")
        return m.group(1)

    # ------------------------------------------------------------------ login

    def login(self) -> dict[str, Any]:
        home = self._get("/").text
        form = {
            "loginEmail": self.email,
            "loginPassword": self.password,
            "loginRememberMe": "true",
            "csrf_token": self._csrf(home),
            "passwordEncrypted": "",
        }
        r = self.http.post(
            CONTROLLER + "Account-Login",
            params={"rurl": "1", "isCheckoutLogin": "false"},
            data=form,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        r.raise_for_status()
        data = r.json()

        if data.get("error") and data.get("isMigratedCustomer") and data.get("salt"):
            import bcrypt

            form["passwordEncrypted"] = bcrypt.hashpw(
                self.password.encode(), data["salt"].encode()
            ).decode()
            r = self.http.post(
                CONTROLLER + "Account-LoginMigratedCustomer",
                params={"rurl": "1", "isCheckoutLogin": "false"},
                data=form,
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            r.raise_for_status()
            data = r.json()

        if not data.get("success"):
            raise TelepizzaError(f"Login failed: {json.dumps(data)[:400]}")
        self.logged_in = True
        return data

    def ensure_login(self) -> None:
        if not self.logged_in:
            self.login()

    # -------------------------------------------------------------- addresses

    def saved_addresses(self) -> list[dict[str, Any]]:
        """Saved delivery addresses, embedded as JSON in the logged-in home."""
        self.ensure_login()
        home = self._get("/").text
        addrs = []
        for m in re.finditer(r'data-select-address="([^"]+)"', home):
            try:
                addrs.append(json.loads(htmllib.unescape(m.group(1))))
            except ValueError:
                continue
        # la home también muestra la dirección actual sin botón si solo hay una
        if not addrs:
            m = re.search(r'data-select-address=\'([^\']+)\'', home)
            if m:
                addrs.append(json.loads(htmllib.unescape(m.group(1))))
        return addrs

    def set_delivery_address(self, address: dict[str, Any] | None = None) -> dict[str, Any]:
        """Bind the session to a store for the given (or default saved) address.

        Necesario para que la carta muestre precios reales de la tienda.
        """
        self.ensure_login()
        if address is None:
            saved = self.saved_addresses()
            if not saved:
                raise TelepizzaError("No saved addresses in the account")
            address = next((a for a in saved if a.get("isSelected")), saved[0])

        lat, lng = address["latitude"], address["longitude"]
        r = self._get(
            CONTROLLER + "Stores-GetStore",
            params={"sid": "", "lat": lat, "lng": lng, "method": "delivery"},
        )
        data = r.json()
        if data.get("error"):
            raise TelepizzaError(f"Stores-GetStore: {data.get('message')}")
        soup = BeautifulSoup(data.get("renderedHtml", ""), "html.parser")
        opts = soup.select("select[name=deliveryHour] option")
        if not opts:
            raise TelepizzaError("No delivery hours available for this address")
        opt = next((o for o in opts if o.get("data-is-first") == "true"), opts[0])

        payload = {
            "shopId": opt["data-store-id"],
            "deliveryHour": opt["value"],
            "shippingMethod": "delivery",
            "minimumAmount": opt.get("data-store-min-amount", ""),
            "waitTime": opt.get("data-store-wait-time", ""),
            "deliveryCost": opt.get("data-store-delivery-cost", ""),
            "customerAddress": {
                "street": address.get("address1", ""),
                "streetNumber": address.get("streetNumber", ""),
                "reference": "",
                "state": address.get("city", ""),
                "postalCode": address.get("postalCode", ""),
                "lat": lat,
                "lng": lng,
                "addressText": address.get("addressText", ""),
                "alternativeArea": "",
                "isMeetingPoint": False,
            },
            "shippingComment": "",
            "redirectAction": "",
            "saveAddress": False,
            "isAsap": opt.get("data-is-first", "false"),
        }
        r2 = self.http.post(
            CONTROLLER + "Stores-SetStore",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        r2.raise_for_status()
        result = r2.json()
        if result.get("error"):
            raise TelepizzaError(f"Stores-SetStore: {json.dumps(result)[:400]}")
        self.store = {
            "shopId": opt["data-store-id"],
            "address": address.get("addressText"),
            "minimumAmount": opt.get("data-store-min-amount"),
            "deliveryCost": opt.get("data-store-delivery-cost"),
            "waitTimeMinutes": opt.get("data-store-wait-time"),
            "firstDeliverySlot": opt["value"],
            "availableSlots": [o["value"] for o in opts],
        }
        return self.store

    def ensure_store(self) -> None:
        if self.store is None:
            self.set_delivery_address()

    # ----------------------------------------------------------------- stores

    def geocode(self, address: str) -> tuple[float, float] | None:
        """Geocode with Nominatim (the web uses Google, whose key is not ours)."""
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1, "countrycodes": "es"},
            headers={"User-Agent": "telepizza-mcp/0.1 (personal use)"},
            timeout=20,
        )
        r.raise_for_status()
        hits = r.json()
        if not hits:
            return None
        return float(hits[0]["lat"]), float(hits[0]["lon"])

    def find_stores(
        self, address: str, lat: float | None = None, lng: float | None = None
    ) -> list[dict[str, Any]]:
        """Search delivery stores near an address (Stores-FindStores needs lat/long)."""
        if lat is None or lng is None:
            coords = self.geocode(address)
            if coords is None:
                raise TelepizzaError(f"Could not geocode address: {address}")
            lat, lng = coords
        r = self._get(
            CONTROLLER + "Stores-FindStores",
            params={"address": address, "lat": lat, "long": lng},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        data = r.json()
        if data.get("error"):
            raise TelepizzaError(str(data.get("message", "FindStores error")))
        keep = (
            "ID", "name", "address1", "city", "postalCode", "phone",
            "storeHoursText", "distance", "latitude", "longitude",
        )
        return [{k: s.get(k) for k in keep} for s in data.get("stores", [])]

    # ------------------------------------------------------------------- menu

    def menu(self, category: str = "pizzas", with_prices: bool = True) -> list[dict[str, Any]]:
        """Products of a menu category. Prices require a store bound to the session."""
        if with_prices:
            self.ensure_store()
        path = MENU_CATEGORIES.get(category, category)
        html = self._get(path).text
        return self._parse_products(html)

    def offers(self) -> list[dict[str, Any]]:
        """Current promotions (/ofertas uses offer tiles, not product tiles)."""
        self.ensure_store()
        soup = BeautifulSoup(self._get("/ofertas").text, "html.parser")
        offers = []
        for tile in soup.select(".offer-tile"):
            link = tile.select_one("[data-name]")
            btn = tile.select_one("[data-promotion-id]")
            title = tile.select_one(".offer-tile__body__title")
            text = tile.select_one(".offer-tile__body__text")
            offers.append({
                "id": (btn and btn.get("data-promotion-id"))
                or (link and link.get("data-id")),
                "name": (link and link.get("data-name"))
                or (title and title.get_text(strip=True)),
                "description": (link and link.get("data-detail"))
                or (text and text.get_text(strip=True)),
            })
        return [o for o in offers if o["id"] or o["name"]]

    def _parse_products(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        products = []
        for tile in soup.select("[data-pid]"):
            gtm = {}
            try:
                gtm = json.loads(tile.get("data-gtmdata") or "{}")
            except ValueError:
                pass
            desc = tile.select_one(".description-short, .product-tile__description-text")
            url_el = tile.select_one('input[name="product-url"]')
            price = gtm.get("price")
            products.append({
                "id": tile.get("data-pid"),
                "name": gtm.get("name"),
                "category": gtm.get("category"),
                "price_eur": None if price in (None, "0.00") else price,
                "description": desc.get_text(strip=True) if desc else None,
                "url": (BASE + url_el["value"]) if url_el and url_el.get("value") else None,
            })
        return products

    # ------------------------------------------------------------------ orders

    def order_history(self) -> list[dict[str, Any]]:
        self.ensure_login()
        html = self._get(CONTROLLER + "Order-History").text
        soup = BeautifulSoup(html, "html.parser")
        orders = []
        for card in soup.select(".order-history-card__card"):
            date = card.select_one(".order-history-card__date")
            btn = card.select_one("[data-order-id]")
            order_id = btn.get("data-order-id") if btn else None
            if not order_id:
                fav = card.select_one("[data-action-url*='orderId=']")
                if fav:
                    m = re.search(r"orderId=(\d+)", fav["data-action-url"])
                    order_id = m.group(1) if m else None
            items = []
            for it in card.select(".order-history-card__item"):
                name = it.select_one(".order-history-card__product-name")
                attrs = [a.get_text(strip=True) for a in it.select(".order-history-card__attributes")]
                items.append({
                    "product": name.get_text(strip=True) if name else None,
                    "details": attrs,
                })
            orders.append({
                "order_id": order_id,
                "date": date.get_text(strip=True) if date else None,
                "items": items,
            })
        return orders

    def order_details(self, order_id: str) -> dict[str, Any]:
        self.ensure_login()
        html = self._get(CONTROLLER + "Order-Details", params={"orderID": order_id}).text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        def grab(pattern: str) -> str | None:
            m = re.search(pattern, text)
            return m.group(1).strip() if m else None

        totals = {}
        summary = soup.select_one(".order-total-summary")
        if summary:
            for row in re.findall(
                r"(Subtotal|Order Discount|Shipping|Shipping Discount|Sales Tax|Total)\s*-?\s*([\d.,]+€|null|-)",
                summary.get_text(" ", strip=True),
            ):
                totals[row[0]] = row[1]
        shipping_method = soup.select_one(".shipping-method")
        return {
            "order_id": grab(r"Order Number:\s*(\d+)") or order_id,
            "date": grab(r"Order Date:\s*([\d/]+)"),
            "shipping_method": shipping_method.get_text(strip=True) if shipping_method else None,
            "payment": grab(r"Payment:\s*(.*?)\s*\d+\s*Items"),
            "totals": totals,
        }

    def close(self) -> None:
        self.http.close()
