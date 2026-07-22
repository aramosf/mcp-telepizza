# 🍕 mcp-telepizza

Servidor **MCP** ([Model Context Protocol](https://modelcontextprotocol.io)) **no oficial** y **solo de lectura** para [telepizza.es](https://www.telepizza.es): consulta la carta con precios, ofertas, tiendas, tus puntos MiTelepi y tu historial de pedidos desde Claude (o cualquier cliente MCP), usando tu propia cuenta.

> 🍕 *"¿Qué ofertas hay hoy?" · "¿Cuánto cuesta una familiar de masa madre?" · "¿Qué pedí la última vez?" · "¿Cuántos puntos tengo?"*

**No puede gastar dinero**: no hay carrito de escritura ni checkout. Todas las herramientas son de consulta.

## 🧠 Cómo funciona

telepizza.es no tiene API pública: es un storefront de **Salesforce Commerce Cloud (Demandware)**. Este servidor replica las llamadas internas que hace la propia web contra sus controladores:

```
https://www.telepizza.es/on/demandware.store/Sites-TelepizzaES-Site/default/<Controller>-<Action>
```

Los detalles no obvios descubiertos por ingeniería inversa están documentados en la cabecera de [`src/telepizza_mcp/client.py`](src/telepizza_mcp/client.py). Los tres que más duelen:

- 🫓 **Los precios dependen de la tienda**: sin tienda fijada en sesión la carta no trae precios. La secuencia es `Stores-GetStore?lat&lng&method=delivery` → `Stores-SetStore`.
- 🫓 `Stores-SetStore` exige **body JSON** — enviándolo como formulario devuelve un 410 que parece un error de CSRF pero no lo es.
- 🫓 El **login** es un POST de formulario con token CSRF; las cuentas antiguas ("migradas") usan además un hash bcrypt en cliente con salt que devuelve el servidor.

## 🚀 Instalación

Requiere Python ≥ 3.11.

```bash
git clone https://github.com/aramosf/mcp-telepizza.git
cd mcp-telepizza
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env   # y rellena tus credenciales de telepizza.es
```

`.env` (no se versiona nunca):

```
TELEPIZZA_EMAIL=tu@email.com
TELEPIZZA_PASSWORD=...
```

### Registro en Claude Code

```bash
claude mcp add telepizza -- $(pwd)/.venv/bin/python -m telepizza_mcp.server
```

El servidor carga el `.env` del propio repo; no hace falta exportar variables. Para Claude Desktop u otros clientes MCP, configura el mismo comando como servidor stdio.

## 🍕 Herramientas

| Tool | Qué hace |
|---|---|
| `login` | Inicia sesión y devuelve el estado de la cuenta |
| `list_saved_addresses` | Direcciones de entrega guardadas en la cuenta |
| `set_delivery_address` | Fija tienda/dirección en sesión (necesario para precios); admite `address_id` |
| `find_stores` | Busca tiendas cercanas a una dirección libre (geocodifica con Nominatim/OSM) |
| `get_store_schedule` | Horario semanal de reparto de las tiendas cercanas a una dirección |
| `get_delivery_slots` | Franjas de entrega disponibles hoy para la dirección guardada |
| `get_menu` | Carta con precios por categoría: `ofertas`, `pizzas`, `entrantes`, `burgers`, `postres`, `bebidas` o una ruta de la web |
| `search_products` | Búsqueda de productos en toda la carta |
| `get_product_details` | Tamaños, masas, bordes e ingredientes de un producto |
| `get_offers` | Promociones vigentes |
| `get_offer_details` | Condiciones completas de una promoción |
| `get_loyalty_status` | Puntos MiTelepi (disponibles/pendientes/canjeados) y movimientos |
| `get_cart` | Carrito actual (solo lectura) |
| `get_order_history` | Pedidos anteriores (id, fecha, artículos) |
| `get_order_details` | Detalle de un pedido: fecha, envío, pago y totales |

## 📝 Notas

- 🕐 **Con la tienda cerrada** el sitio no permite fijar tienda: la carta se devuelve sin precios y `get_delivery_slots`/`get_offer_details` reportan la indisponibilidad con el mensaje del sitio.
- 🔐 Las credenciales viven solo en tu `.env` local (ignorado por git) y solo se envían a telepizza.es.
- 🧱 Si Telepizza cambia el frontal, los parsers pueden necesitar ajustes.

## ⚖️ Aviso

Proyecto personal, **sin afiliación alguna con Telepizza**. Automatiza el acceso a tu propia cuenta con tus propias credenciales, igual que lo haría tu navegador; revisa los términos de uso del sitio y úsalo con moderación. El software se ofrece tal cual, sin garantías (ver [LICENSE](LICENSE)).

---

🍕 Hecho con hambre y un poco de ingeniería inversa.
