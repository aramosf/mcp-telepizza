# telepizza-mcp

Servidor MCP (stdio) **solo de consulta** para telepizza.es: carta con precios,
ofertas, tiendas, direcciones guardadas e historial de pedidos de tu cuenta.
Sin carrito ni checkout (no puede gastar dinero).

telepizza.es no tiene API pública: la web es un storefront de Salesforce
Commerce Cloud (Demandware) y este servidor replica las llamadas internas de la
propia web (ver notas de ingeniería inversa en la cabecera de
`src/telepizza_mcp/client.py`).

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env   # y rellena tus credenciales
```

`.env` (no se versiona):

```
TELEPIZZA_EMAIL=tu@email.com
TELEPIZZA_PASSWORD=...
```

## Registro en Claude Code

```bash
claude mcp add telepizza -- /home/aramosf/telepizza-mcp/.venv/bin/python -m telepizza_mcp.server
```

(El servidor carga el `.env` del propio repo, no hace falta exportar variables.)

## Tools

| Tool | Qué hace |
|---|---|
| `login` | Inicia sesión y devuelve el estado de la cuenta |
| `list_saved_addresses` | Direcciones de entrega guardadas en la cuenta |
| `set_delivery_address` | Fija tienda/dirección en sesión (necesario para precios); admite `address_id` |
| `find_stores` | Busca tiendas cercanas a una dirección libre (geocodifica con Nominatim) |
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

## Notas

- Los precios dependen de la tienda: `get_menu`/`get_offers` fijan
  automáticamente la dirección guardada por defecto si aún no hay tienda en
  sesión. **Con la tienda cerrada** el sitio no permite fijar tienda y la
  carta se devuelve sin precios (y `get_delivery_slots`/`get_offer_details`
  reportan la indisponibilidad).
- El login soporta el flujo de cuentas "migradas" (hash bcrypt en cliente con
  salt del servidor), aunque las cuentas normales no lo necesitan.
- Scraping de superficie privada propia: usa tu cuenta y tus datos. Si
  Telepizza cambia el frontal, los parsers pueden requerir ajustes.
