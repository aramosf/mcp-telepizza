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
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.telepizza.es"
CONTROLLER = "/on/demandware.store/Sites-TelepizzaES-Site/default/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

SIZES = {"individual": "16", "mediana": "20", "familiar": "21"}


def parse_price(text: str | None) -> float | None:
    """Normalize a price string to euros as float.

    Acepta tanto "23.95" (data-gtm) como "23,95€" / "1.234,50 €" (HTML es_ES).
    Devuelve None si no hay número o es 0.
    """
    if not text:
        return None
    t = text.replace("€", "").replace("EUR", "").strip()
    if not t:
        return None
    # es_ES: si hay coma, es el separador decimal y el punto es de miles.
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    if not m:
        return None
    val = float(m.group(0))
    return val if val != 0 else None

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
    def __init__(self, email: str, password: str, session_file: str | None = None):
        self.email = email
        self.password = password
        self.logged_in = False
        self.store: dict[str, Any] | None = None
        self._cache: dict[str, tuple[float, Any]] = {}
        self.cache_ttl = 300.0
        self._store_fail: tuple[float, str] | None = None
        self.http = httpx.Client(
            base_url=BASE,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "es-ES,es;q=0.9",
            },
            follow_redirects=True,
            timeout=30,
        )
        # Persistencia de sesión: por defecto en la caché del usuario, por email.
        if session_file is None:
            base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
            safe = re.sub(r"[^a-z0-9]+", "_", email.lower())
            session_file = str(Path(base) / "mcp-telepizza" / f"{safe}.cookies")
        self._session_file = Path(session_file)
        self._load_session()

    # -------------------------------------------------------- session on disk

    def _load_session(self) -> None:
        """Carga cookies de una sesión anterior para evitar reloguear.

        No garantiza validez; los accesos autenticados se auto-curan
        (_authed_html) reloguéandose si la sesión caducó.
        """
        try:
            data = json.loads(self._session_file.read_text())
        except (OSError, ValueError):
            return
        for name, value in data.get("cookies", {}).items():
            self.http.cookies.set(name, value, domain="www.telepizza.es")
        if self.http.cookies.get("dwsid"):
            self.logged_in = True

    def _save_session(self) -> None:
        try:
            self._session_file.parent.mkdir(parents=True, exist_ok=True)
            self._session_file.write_text(
                json.dumps({"cookies": dict(self.http.cookies)})
            )
            os.chmod(self._session_file, 0o600)
        except OSError:
            pass

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
        self._save_session()
        return data

    def ensure_login(self) -> None:
        if not self.logged_in:
            self.login()

    @staticmethod
    def _looks_logged_out(html: str) -> bool:
        # Toda página incluye el modal de login; solo la sesión activa muestra
        # "Cerrar sesión" en la cabecera.
        return "Cerrar sesión" not in html and "login-form-email" in html

    def _authed_html(self, path: str, **kw) -> str:
        """GET an account page, re-logging in once if the session expired."""
        self.ensure_login()
        html = self._get(path, **kw).text
        if self._looks_logged_out(html):
            self.logged_in = False
            self.login()
            html = self._get(path, **kw).text
        return html

    def _cached(self, key: str, fetch):
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        value = fetch()
        self._cache[key] = (now + self.cache_ttl, value)
        return value

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

    def _store_options(self, lat: float, lng: float) -> list:
        """Delivery-hour <option> elements for the store serving lat/lng.

        Cada opción lleva la tienda en data-store-* (id, mínimo, coste, espera).
        Falla con el mensaje del sitio si la tienda está cerrada.
        """
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
        return opts

    def _default_address(self, address: dict[str, Any] | None = None) -> dict[str, Any]:
        if address is not None:
            return address
        saved = self.saved_addresses()
        if not saved:
            raise TelepizzaError("No saved addresses in the account")
        return next((a for a in saved if a.get("isSelected")), saved[0])

    def set_delivery_address(self, address: dict[str, Any] | None = None) -> dict[str, Any]:
        """Bind the session to a store for the given (or default saved) address.

        Necesario para que la carta muestre precios reales de la tienda.
        """
        self.ensure_login()
        address = self._default_address(address)

        lat, lng = address["latitude"], address["longitude"]
        opts = self._store_options(lat, lng)
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
        self._cache.clear()  # los precios dependen de la tienda
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

    def _try_ensure_store(self) -> str | None:
        """Best-effort store binding; returns the site's message if unavailable.

        Fuera de horario Stores-GetStore falla ("Esta tienda no se encuentra
        disponible por el momento") y la carta se sirve sin precios.
        """
        if self.store is not None:
            return None
        if self._store_fail and self._store_fail[0] > time.monotonic():
            return self._store_fail[1]
        try:
            self.ensure_store()
            self._store_fail = None
            return None
        except TelepizzaError as e:
            self._store_fail = (time.monotonic() + self.cache_ttl, str(e))
            return str(e)

    def delivery_slots(self, address: dict[str, Any] | None = None) -> dict[str, Any]:
        """Available delivery time slots for a saved address (default if None)."""
        self.ensure_login()
        address = self._default_address(address)
        opts = self._store_options(address["latitude"], address["longitude"])
        first = opts[0]
        return {
            "address": address.get("addressText"),
            "shopId": first.get("data-store-id"),
            "minimumAmount": first.get("data-store-min-amount"),
            "deliveryCost": first.get("data-store-delivery-cost"),
            "waitTimeMinutes": first.get("data-store-wait-time"),
            "slots": [o.get("value") for o in opts if o.get("value")],
        }

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

    def store_schedule(self, address: str) -> list[dict[str, Any]]:
        """Weekly delivery schedule of the stores near an address."""
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
        result = []
        for s in data.get("stores", []):
            schedule = {}
            sched_html = s.get("storeSchedule") or ""
            soup = BeautifulSoup(sched_html, "html.parser")
            for row in soup.select(".clearfix"):
                spans = row.find_all("span")
                if len(spans) >= 2:
                    day = spans[0].get_text(strip=True).rstrip(".:")
                    schedule[day] = spans[1].get_text(strip=True)
            result.append({
                "ID": s.get("ID"),
                "name": s.get("name"),
                "city": s.get("city"),
                "today": s.get("storeHoursText"),
                "weekly_delivery_schedule": schedule,
            })
        return result

    # ------------------------------------------------------------------- menu

    def menu(self, category: str = "pizzas", with_prices: bool = True) -> list[dict[str, Any]]:
        """Products of a menu category. Prices require a store bound to the session."""
        if with_prices:
            self._try_ensure_store()
        path = MENU_CATEGORIES.get(category, category)
        return self._cached(
            f"menu:{path}", lambda: self._parse_products(self._get(path).text)
        )

    def search_products(self, query: str) -> list[dict[str, Any]]:
        """Full-text product search (Search-Show, SFCC standard)."""
        self._try_ensure_store()
        html = self._get(
            CONTROLLER + "Search-Show", params={"q": query}
        ).text
        return self._parse_products(html)

    def product_details(self, product_id: str) -> dict[str, Any]:
        """Sizes, dough/sauce options and ingredients of a product (quick view)."""
        self._try_ensure_store()
        html = self._get(
            CONTROLLER + "Product-ShowQuickView",
            params={"pid": product_id},
            headers={"X-Requested-With": "XMLHttpRequest"},
        ).text
        soup = BeautifulSoup(html, "html.parser")

        name_el = soup.select_one(
            ".product-name, .pdp-title, .modal-title, h1, h2"
        )
        sizes = []
        for o in soup.select("[data-select-variation][data-value-id]"):
            sizes.append({
                "label": o.get("data-value-id"),
                "value": o.get("data-attr-value"),
            })
        option_groups = []
        for ul in soup.select("ul.pdp-option"):
            items = [li.get_text(" ", strip=True) for li in ul.select("li")]
            items = [i for i in items if i]
            option_groups.append({
                "id": ul.get("data-attr-id"),
                "options": items or [ul.get_text(" ", strip=True)],
            })
        m = re.search(r'data-price="([\d.]+)"', html)
        desc = soup.select_one(".description-short, .product-description, .short-description")
        return {
            "id": product_id,
            "name": name_el.get_text(" ", strip=True) if name_el else None,
            "price": parse_price(m.group(1)) if m else None,
            "description": desc.get_text(" ", strip=True) if desc else None,
            "sizes": sizes,
            "option_groups": option_groups,
        }

    def offers(self) -> list[dict[str, Any]]:
        """Current promotions (/ofertas uses offer tiles, not product tiles)."""
        self._try_ensure_store()
        return self._cached("offers", self._fetch_offers)

    def _fetch_offers(self) -> list[dict[str, Any]]:
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

    def offer_details(self, offer_id: str) -> dict[str, Any]:
        """Full conditions/content of one promotion (Offers-Details modal).

        La disponibilidad depende de la tienda en sesión; con tienda cerrada
        el sitio responde que la promoción no está disponible.
        """
        store_msg = self._try_ensure_store()
        html = self._get(
            CONTROLLER + "Offers-Details",
            params={"promotionID": offer_id},
            headers={"X-Requested-With": "XMLHttpRequest"},
        ).text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        if "no cumple los requisitos" in text or "no está disponible" in text:
            return {
                "id": offer_id,
                "available": False,
                "message": text[:300],
                "store_note": store_msg,
            }
        title = soup.select_one(".modal-title, h1, h2, .offer-tile__body__title")
        products = self._parse_products(html)
        return {
            "id": offer_id,
            "available": True,
            "title": title.get_text(" ", strip=True) if title else None,
            "text": text[:1500],
            "products": products or None,
        }

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
            products.append({
                "id": tile.get("data-pid"),
                "name": gtm.get("name"),
                "category": gtm.get("category"),
                "price": parse_price(gtm.get("price")),
                "description": desc.get_text(strip=True) if desc else None,
                "url": (BASE + url_el["value"]) if url_el and url_el.get("value") else None,
            })
        return products

    # ------------------------------------------------------------------ orders

    def order_history(self) -> list[dict[str, Any]]:
        html = self._authed_html(CONTROLLER + "Order-History")
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
        html = self._authed_html(
            CONTROLLER + "Order-Details", params={"orderID": order_id}
        )
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

    # ----------------------------------------------------------- loyalty/cart

    def loyalty_status(self) -> dict[str, Any]:
        """MiTelepi points: available/pending/redeemed and last movements."""
        html = self._authed_html(CONTROLLER + "Loyalty-MyActivity")
        soup = BeautifulSoup(html, "html.parser")
        box = soup.select_one(".loyalty-transactions") or soup

        def to_int(num: str) -> int:
            return int(re.sub(r"[^\d-]", "", num) or 0)

        summary = {}
        for card in box.select(".point-card"):
            text = card.get_text(" ", strip=True)
            m = re.search(r"([\d.]+)\s*Puntos\s+(\w+)", text)
            if m:
                summary[f"points_{m.group(2).lower()}"] = to_int(m.group(1))

        movements = []
        text = box.get_text(" ", strip=True)
        for m in re.finditer(
            r"([+-]?\s*[\d.]+)\s*pts\s*(\d{2}/\d{2}/\d{4})\s*(.*?)(?=[+-]?\s*[\d.]+\s*pts\s*\d{2}/|$)",
            text,
        ):
            movements.append({
                "points": to_int(m.group(1)),
                "date": m.group(2),
                "description": m.group(3).strip()[:160],
            })
        return {"summary": summary, "movements": movements}

    def loyalty_rewards(self) -> list[dict[str, Any]]:
        """MiTelepi redeemable rewards: what points buy and at what price."""
        html = self._authed_html(CONTROLLER + "Loyalty-Dashboard")
        soup = BeautifulSoup(html, "html.parser")
        rewards = []
        for card in soup.select(".promo-card-item"):
            trigger = card.select_one("[data-promotion-id]")
            title = card.select_one(".title")
            text = card.select_one(".promo-tooltip .text")
            footer = card.select_one(".promo-card-footer")
            points = price = None
            if footer:
                ftxt = footer.get_text(" ", strip=True)
                pm = re.search(r"\+?\s*([\d.]+)\s*Puntos", ftxt)
                if pm:
                    points = int(re.sub(r"[^\d]", "", pm.group(1)))
                em = re.search(r"[\d.,]+\s*€", ftxt)
                if em:
                    price = parse_price(em.group(0))
            rewards.append({
                "id": trigger.get("data-promotion-id") if trigger else None,
                "title": title.get_text(strip=True) if title else None,
                "description": text.get_text(" ", strip=True) if text else None,
                "points": points,
                "price": price,
                "channel": card.get("data-tab-content"),  # delivery / takeaway
            })
        return [r for r in rewards if r["id"] or r["title"]]

    def status(self) -> dict[str, Any]:
        """Session, store and opening status in one call."""
        login_error = None
        try:
            self.ensure_login()
        except Exception as e:  # credenciales mal, web caída…
            login_error = str(e)[:200]
        result: dict[str, Any] = {
            "logged_in": self.logged_in,
            "login_error": login_error,
            "store_in_session": self.store,
        }
        if not self.logged_in:
            return result
        try:
            address = self._default_address()
            result["default_address"] = address.get("addressText")
            try:
                opts = self._store_options(address["latitude"], address["longitude"])
                first = opts[0]
                result["store_open"] = True
                result["store_id"] = first.get("data-store-id")
                result["next_delivery_slot"] = first.get("value")
                result["minimum_amount"] = parse_price(first.get("data-store-min-amount"))
            except TelepizzaError as e:
                result["store_open"] = False
                result["store_message"] = str(e)[:200]
                stores = self.find_stores(
                    address.get("addressText", ""),
                    lat=address["latitude"],
                    lng=address["longitude"],
                )
                if stores:
                    result["store_hours_today"] = stores[0].get("storeHoursText")
        except TelepizzaError as e:
            result["address_error"] = str(e)[:200]
        return result

    def _minicart_html(self) -> str:
        return self._get(
            CONTROLLER + "Cart-MiniCartShow",
            params={"isToggleable": "true", "isCheckoutPage": "false"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        ).text

    @staticmethod
    def _parse_cart(html: str) -> dict[str, Any]:
        """Structured cart from the mini-cart HTML.

        Cada línea de producto se ancla en el <input class="quantity"> que
        lleva data-uuid / data-pid / data-product-name; el importe de línea
        está en .line-item-total-price-amount.item-total-<uuid>. Las ofertas
        se quitan con Cart-RemoveOffer (data-url completa en el HTML).
        """
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        empty = "carrito está vacío" in text
        addr = soup.select_one(".address")

        items = []
        for inp in soup.select("input.quantity[data-uuid]"):
            uuid = inp.get("data-uuid")
            pid = inp.get("data-pid", "")
            base, _, size = pid.partition("-")
            total_el = soup.select_one(f".line-item-total-price-amount.item-total-{uuid}")
            line_total = None
            if total_el:
                line_total = parse_price(total_el.get_text(" ", strip=True))
            try:
                qty = int(inp.get("value") or "1")
            except ValueError:
                qty = 1
            items.append({
                "uuid": uuid,
                "pid": pid,
                "name": inp.get("data-product-name"),
                "size": size or None,
                "quantity": qty,
                "line_total": line_total,
            })

        offers = []
        for el in soup.select('[data-url*="Cart-RemoveOffer"]'):
            url = (el.get("data-url") or "").replace("&amp;", "&")
            label = el.get("data-promotion-name") or el.get("aria-label")
            offers.append({"remove_url": url, "label": label})

        total = None
        m = re.search(r"Importe total:\s*([\d.,]+\s*€)", text)
        if m:
            total = parse_price(m.group(1))
        return {
            "delivery_address": addr.get_text(" ", strip=True) if addr else None,
            "empty": empty,
            "items": items,
            "offers": offers,
            "total": total,
        }

    def cart(self) -> dict[str, Any]:
        """Structured snapshot of the current cart (read-only)."""
        self.ensure_login()
        return self._parse_cart(self._minicart_html())

    # ------------------------------------------------ cart WRITE (no payment)

    def add_to_cart(
        self,
        product_id: str,
        size: str | None = None,
        quantity: int = 1,
        options: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Add a product to the cart (no payment).

        - Pizzas con tamaño: pasa size="individual"|"mediana"|"familiar" o un
          product_id que ya incluya el sufijo ("<id>-mediana"). Si el producto
          tiene tallas y no indicas ninguna, se lanza un error con las opciones.
        - options: campos extra de configuración (p.ej. masa) que se envían tal
          cual al formulario Cart-AddProduct.
        """
        self.ensure_store()
        base, _, suffix = product_id.partition("-")
        chosen = (size or suffix or "").lower()

        sizes = self.product_details(base).get("sizes") or []
        size_labels = {s["label"].lower(): s["label"] for s in sizes}
        if sizes:
            if not chosen:
                raise TelepizzaError(
                    f"Product {base} needs a size; choose one of "
                    f"{sorted(size_labels) or list(SIZES)}"
                )
            if chosen not in size_labels and chosen not in SIZES:
                raise TelepizzaError(
                    f"Unknown size {chosen!r}; options: {sorted(size_labels) or list(SIZES)}"
                )
            pid = f"{base}-{chosen}"
        else:
            pid = product_id  # producto sin tallas (bebida, entrante…)

        form = {"pid": pid, "quantity": str(quantity)}
        if options:
            form.update(options)
        r = self.http.post(
            CONTROLLER + "Cart-AddProduct",
            data=form,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            data = {}
        if data.get("error") or data.get("errorMessage"):
            raise TelepizzaError(
                str(data.get("errorMessage") or data.get("message") or data)[:300]
            )
        return {"message": data.get("message"), "cart": self.cart()}

    def reorder(self, order_id: str) -> dict[str, Any]:
        """Fill the cart with the items of a previous order (Order-Reorder)."""
        self.ensure_store()
        r = self.http.post(
            CONTROLLER + "Order-Reorder",
            data={"orderID": order_id, "historyPage": "true"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise TelepizzaError(str(data.get("message") or data)[:300])
        return {
            "message": data.get("message"),
            "reordered_all_items": not data.get("isEmptyCart", False),
            "cart": self.cart(),
        }

    def _remove_line(self, pid: str, uuid: str) -> None:
        self._get(
            CONTROLLER + "Cart-RemoveProductLineItem",
            params={"pid": pid, "uuid": uuid},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    def remove_from_cart(self, uuid: str) -> dict[str, Any]:
        """Remove one product line by its uuid (from cart()['items'])."""
        self.ensure_login()
        snapshot = self._parse_cart(self._minicart_html())
        line = next((i for i in snapshot["items"] if i["uuid"] == uuid), None)
        if line is None:
            raise TelepizzaError(f"No cart line with uuid {uuid}")
        self._remove_line(line["pid"], uuid)
        return {"cart": self.cart()}

    def clear_cart(self) -> dict[str, Any]:
        """Empty the cart completely. Raises if it could not be emptied."""
        for _ in range(30):
            snapshot = self._parse_cart(self._minicart_html())
            if snapshot["empty"]:
                return snapshot
            if snapshot["items"]:
                self._remove_line(snapshot["items"][0]["pid"], snapshot["items"][0]["uuid"])
            elif snapshot["offers"] and snapshot["offers"][0]["remove_url"]:
                self._get(
                    snapshot["offers"][0]["remove_url"],
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
            else:
                break  # ni líneas ni ofertas pero no marca vacío: evita bucle
        final = self._parse_cart(self._minicart_html())
        if not final["empty"]:
            raise TelepizzaError(
                f"Could not empty cart; still {len(final['items'])} item(s), "
                f"{len(final['offers'])} offer(s)"
            )
        return final

    def toggle_favorite_order(self, order_id: str) -> dict[str, Any]:
        """Mark/unmark a past order as favorite."""
        self.ensure_login()
        r = self.http.post(
            CONTROLLER + "Order-ToogleFavoriteOrder",
            params={"orderId": order_id},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            return {"status": r.status_code}

    def close(self) -> None:
        self.http.close()
