# 🍕 mcp-telepizza

Servidor **MCP** ([Model Context Protocol](https://modelcontextprotocol.io)) **no oficial** y **solo de lectura** para [telepizza.es](https://www.telepizza.es): consulta la carta con precios, ofertas, tiendas, tus puntos MiTelepi y tu historial de pedidos desde Claude (o cualquier cliente MCP), usando tu propia cuenta.

> 🍕 *"¿Qué ofertas hay hoy?" · "¿Cuánto cuesta una familiar de masa madre?" · "¿Qué pedí la última vez?" · "¿Cuántos puntos tengo?"*

**No puede gastar dinero**: no existe checkout ni ninguna herramienta de pago. Hay herramientas de consulta y unas pocas de escritura *sin coste* (llenar/vaciar el carrito, marcar favoritos) claramente marcadas como `WRITE`.

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

### Registro en Codex CLI (OpenAI)

Codex CLI habla MCP por **stdio**, igual que Claude Code. Añade el servidor a `~/.codex/config.toml`:

```toml
[mcp_servers.telepizza]
command = "/ruta/a/mcp-telepizza/.venv/bin/python"
args = ["-m", "telepizza_mcp.server"]
# el .env del repo se carga solo; si prefieres, pásalas aquí:
# env = { TELEPIZZA_EMAIL = "tu@email.com", TELEPIZZA_PASSWORD = "..." }
```

O con el comando:

```bash
codex mcp add telepizza -- /ruta/a/mcp-telepizza/.venv/bin/python -m telepizza_mcp.server
```

### Registro en ChatGPT

ChatGPT (web/escritorio) admite servidores MCP como **conectores personalizados en modo desarrollador**, pero solo **remotos por HTTP/SSE** — no lanza procesos locales por stdio. Este servidor es stdio, así que para usarlo desde ChatGPT necesitas exponerlo como endpoint remoto, por ejemplo con un puente [`mcp-remote`](https://github.com/geelen/mcp-remote)/`supergateway` y una URL accesible (con su capa de autenticación). Para uso local, **Codex CLI o Claude Code son la vía directa**.

> 📄 ¿Quieres entender cómo funciona telepizza.es por dentro (plataforma, endpoints, sesión, precios por tienda, puntos)? Está todo en [`docs/TELEPIZZA_INTERNALS.md`](docs/TELEPIZZA_INTERNALS.md).

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
| `get_loyalty_rewards` | Catálogo de canjes: a qué equivalen tus puntos (puntos + precio + canal) |
| `get_cart` | Carrito actual |
| `get_order_history` | Pedidos anteriores (id, fecha, artículos) |
| `get_order_details` | Detalle de un pedido: fecha, envío, pago y totales |
| `status` | Estado de sesión y tienda: abierta/cerrada, próxima franja, horario de hoy |

### ✍️ Herramientas de escritura (sin coste, pero modifican tu cuenta)

| Tool | Qué hace |
|---|---|
| `add_to_cart` | Añade un producto al carrito real (`<id>-<talla>` para productos con tamaño) |
| `reorder` | Llena el carrito con un pedido anterior |
| `remove_from_cart` | Quita una línea del carrito (usa el `remove_url` que devuelve `get_cart`) |
| `clear_cart` | Vacía el carrito |
| `toggle_favorite_order` | Marca/desmarca un pedido como favorito |

Ninguna de ellas paga ni confirma pedidos — el checkout no existe en este MCP — pero **sí modifican el estado real de tu cuenta**.

## 🔓 Permisos en Claude Code: lectura sin prompts, escritura con confirmación

Por defecto Claude Code pide permiso en cada llamada a una tool MCP. Para usar el servidor con fluidez, añade a tu `settings.json` (`~/.claude/settings.json` global o `.claude/settings.json` del proyecto) una allowlist **solo con las herramientas de lectura**:

```json
{
  "permissions": {
    "allow": [
      "mcp__telepizza__status",
      "mcp__telepizza__login",
      "mcp__telepizza__list_saved_addresses",
      "mcp__telepizza__set_delivery_address",
      "mcp__telepizza__find_stores",
      "mcp__telepizza__get_store_schedule",
      "mcp__telepizza__get_delivery_slots",
      "mcp__telepizza__get_menu",
      "mcp__telepizza__search_products",
      "mcp__telepizza__get_product_details",
      "mcp__telepizza__get_offers",
      "mcp__telepizza__get_offer_details",
      "mcp__telepizza__get_loyalty_status",
      "mcp__telepizza__get_loyalty_rewards",
      "mcp__telepizza__get_cart",
      "mcp__telepizza__get_order_history",
      "mcp__telepizza__get_order_details"
    ]
  }
}
```

> ⚠️ **Aviso de seguridad**
>
> - **No añadas `mcp__telepizza` a secas** (el servidor entero): eso auto-aprobaría también las herramientas de escritura.
> - Las herramientas `WRITE` (`add_to_cart`, `reorder`, `remove_from_cart`, `clear_cart`, `toggle_favorite_order`) **deben quedarse fuera de la allowlist** para que Claude te pida confirmación cada vez: modifican el carrito y los favoritos de tu cuenta real. No pueden gastar dinero (no hay checkout), pero un carrito lleno por error acaba en sorpresas si luego rematas el pedido a mano.
> - Estas herramientas usan tus credenciales reales de telepizza.es; concede permisos solo en máquinas de confianza.

## 🎁 Puntos MiTelepi

- `get_loyalty_status` te dice cuántos puntos tienes (disponibles, pendientes de verificar y canjeados) y sus movimientos con caducidades.
- `get_loyalty_rewards` lista el catálogo de canjes: cada recompensa con su **coste en puntos**, el **precio resultante** y el canal (a domicilio o recoger). Ejemplo: "Pizza mediana 5 ingredientes → 1.600 puntos + 9,95€ a domicilio".
- **Cómo se usan**: el canje se materializa al hacer un pedido — con puntos suficientes, la promoción aparece disponible en el flujo de ofertas/carrito de la web o la app (máximo 3 canjes distintos por pedido). Este MCP no confirma pedidos, así que el canje se remata en la web/app.
- 💡 Los puntos caducan (los movimientos de `get_loyalty_status` lo muestran): revisa el saldo de vez en cuando.

## 📝 Notas

- 🕐 **Con la tienda cerrada** el sitio no permite fijar tienda: la carta se devuelve sin precios, `status` te dice el horario de hoy, y `get_delivery_slots`/`get_offer_details` reportan la indisponibilidad con el mensaje del sitio.
- ⚡ Carta y ofertas se cachean 5 minutos por proceso para no machacar la web.
- 🔁 Si la sesión caduca a mitad de conversación, el cliente reloguea solo.
- 🔐 Las credenciales viven solo en tu `.env` local (ignorado por git) y solo se envían a telepizza.es.
- 🧪 Los tests corren offline contra fixtures HTML **sanitizadas** (sin datos personales) capturadas del sitio real; el CI de GitHub Actions no necesita credenciales.
- 🧱 Si Telepizza cambia el frontal, los parsers pueden necesitar ajustes (los tests avisan).

## ⚖️ Aviso

Proyecto personal, **sin afiliación alguna con Telepizza**. Automatiza el acceso a tu propia cuenta con tus propias credenciales, igual que lo haría tu navegador; revisa los términos de uso del sitio y úsalo con moderación. El software se ofrece tal cual, sin garantías (ver [LICENSE](LICENSE)).

---

🍕 Hecho con hambre y un poco de ingeniería inversa.
