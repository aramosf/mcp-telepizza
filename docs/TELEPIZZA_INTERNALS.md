# 🍕 Telepizza.es — notas de ingeniería inversa

Documento de referencia para entender **cómo funciona por dentro telepizza.es** y,
con ello, el código de este MCP. Todo lo aquí descrito se obtuvo observando el
tráfico y los *bundles* JavaScript públicos del sitio (julio 2026); **no hay API
oficial ni documentación de Telepizza**. Si el sitio cambia, actualiza este
documento junto con los parsers y las fixtures de `tests/`.

> Fuente de verdad del comportamiento: los métodos de
> [`src/telepizza_mcp/client.py`](../src/telepizza_mcp/client.py). Este documento
> explica el *porqué*; el código, el *cómo* exacto.

---

## 1. Plataforma

| Aspecto | Detalle |
|---|---|
| **E-commerce** | **Salesforce Commerce Cloud (SFCC / Demandware)**, tema **SFRA** (Storefront Reference Architecture) |
| **Site ID** | `Sites-TelepizzaES-Site` |
| **Locale** | `default` (es_ES); existe `ES`/`CA` (catalán) vía `Page-SetLocale` |
| **Moneda / TZ** | EUR / `Europe/Madrid` (visible en la cookie `dwac_*`) |
| **Build estático** | versión fechada en la ruta de assets: `.../v1784747713735/...` (cambia en cada despliegue; úsala como *cache-buster*, no la fijes) |
| **CDN de assets** | `statices.telepizza.com` (JS/CSS/imágenes de tema), `images.telepizza.com` (campañas) |
| **Analítica / perso.** | Demandware Analytics (`dwanalytics`, `dwac`), CQuotient (`cdn.cquotient.com`), Salesforce Marketing Cloud / iGoDigital (`collect.igodigital.com`) |
| **Mapas** | Google Maps JS API + Places (geocodificación de direcciones en cliente, con API key pública restringida por dominio incrustada en el JS) |
| **Métodos de pago mostrados** | `CASH, PayPal, REDSYS, CARD_DELIVERY, BIZUM_DELIVERY, GOOGLE_PAY` (este MCP **no** toca ninguno) |

### Patrón de URLs (controladores SFRA)

Todas las llamadas "de aplicación" tienen esta forma:

```
https://www.telepizza.es/on/demandware.store/Sites-TelepizzaES-Site/default/<Controller>-<Action>
```

Además hay **rutas "bonitas"** que SFCC mapea a controladores internos:

| Ruta pública | Equivale a |
|---|---|
| `/comida-a-domicilio/<categoria>` | `Search-Show` (listado de categoría) |
| `/ofertas` | página de promociones (offer tiles) |
| `/mitelepi` | `Loyalty-Dashboard` |
| `/secure/orderhistory` | `Order-History` (301 desde el controlador) |
| `/product/<slug>-<pid>.html` | ficha de producto |

---

## 2. Autenticación y sesión

### Cookies

- `dwsid` — session id de Demandware (la sesión de navegación).
- `dwsecuretoken*`, `dwac_*` — tokens de seguridad/analítica.
- La sesión de **cliente logueado** se mantiene con esas cookies; no hay bearer token ni OAuth.

### Token CSRF

- Cada página HTML incluye `<input type="hidden" name="csrf_token" value="...">`.
- Es **de un solo uso / ligado a la sesión**; hay que releerlo de una página fresca antes de cada POST que lo exija (login, `Stores-SetStore`).

### Flujo de login (`Account-Login`)

`POST` **form-encoded** con:

```
loginEmail, loginPassword, loginRememberMe=true, csrf_token, passwordEncrypted=""
```

Respuesta JSON `{ success, redirectUrl, loyaltyContactId, ... }`.

**Caso "cliente migrado"** (cuentas antiguas de la plataforma anterior): la primera
respuesta trae `{ error, isMigratedCustomer:true, salt }`. Entonces el cliente
calcula `bcrypt(password, salt)` **en el navegador** (librería `bcryptjs`), lo pone
en `passwordEncrypted` y reenvía el mismo formulario a
**`Account-LoginMigratedCustomer`**. → replicado en `client.login()`.

### Detección de sesión caducada

No hay endpoint de "whoami". Heurística usada: una página de cuenta muestra
**"Cerrar sesión"** en la cabecera solo si hay sesión; si en su lugar aparece el
modal de login (`login-form-email`) la sesión expiró. → `client._looks_logged_out()`
dispara un relogin automático (`client._authed_html()`).

---

## 3. Tiendas, dirección y por qué aparecen (o no) los precios

**Regla de oro:** el catálogo **no muestra precios hasta que hay una tienda
asignada a la sesión**. La asignación depende de una dirección con coordenadas.

### Direcciones guardadas

Van **incrustadas en el HTML de la home logueada**, como JSON dentro del atributo
`data-select-address` de cada botón de dirección:

```json
{"ID":"…","address1":"Calle …","streetNumber":"12","city":"Madrid",
 "postalCode":"28000","latitude":40.41,"longitude":-3.70,
 "addressText":"Calle …, 12, …, España","isSelected":true}
```

→ `client.saved_addresses()` las extrae con regex + `html.unescape`.

### Geocodificación

El sitio geocodifica direcciones **en cliente con Google Places** antes de buscar
tienda. Como no tenemos su API key, el MCP geocodifica con **Nominatim (OSM)** en
`client.geocode()` para `find_stores`/`store_schedule`. Para direcciones guardadas
no hace falta: ya traen lat/long.

### Buscar tienda (`Stores-FindStores`)

`GET` con `address`, `lat`, `long` (los tres; solo `address` da
"dirección incompleta"). Devuelve JSON `{ stores:[…] }`. Cada tienda incluye
`ID`, dirección, teléfono, `storeHoursText`, y **`storeSchedule`** (un fragmento
HTML con el horario semanal de reparto que el MCP parsea en `store_schedule()`).

### Asignar tienda — los dos escalones y la trampa del 410

1. **`Stores-GetStore`** — `GET ?sid=&lat=&lng=&method=delivery`. Devuelve
   `{ store, renderedHtml, … }`. El `renderedHtml` contiene un
   `<select name="deliveryHour">` cuyas `<option>` llevan **toda la info de la
   tienda en atributos `data-*`**: `data-store-id`, `data-store-min-amount`,
   `data-store-delivery-cost`, `data-store-wait-time`, `data-is-first` (el primer
   hueco = ASAP). → `client._store_options()`.

2. **`Stores-SetStore`** — fija la tienda en sesión. ⚠️ **Exige body JSON**
   (`Content-Type: application/json`). Enviado como formulario responde **HTTP 410**
   con un JSON que *parece* un error genérico de CSRF ("For technical reasons…")
   pero **no lo es**: es simplemente que espera JSON. Este fue el mayor escollo del
   reverse engineering. El body:

   ```json
   {"shopId","deliveryHour","shippingMethod":"delivery",
    "minimumAmount","waitTime","deliveryCost",
    "customerAddress":{"street","streetNumber","state","postalCode","lat","lng",
                       "addressText","isMeetingPoint":false},
    "saveAddress":false,"isAsap"}
   ```

   Respuesta OK: `{ error:false, redirectUrl:"/ofertas" }`. A partir de ahí el
   catálogo trae precios. → `client.set_delivery_address()`.

### Tienda cerrada

Fuera de horario, `Stores-GetStore` responde `error:true`
("Esta tienda no se encuentra disponible por el momento") y **no se puede fijar
tienda**: el catálogo se sirve **sin precios**. El MCP degrada con elegancia
(`client._try_ensure_store()` devuelve el mensaje en vez de reventar) y memoiza el
fallo 5 min. La tool `status` reporta abierto/cerrado + horario de hoy.

---

## 4. Catálogo y productos

### Listados de categoría

Las páginas `/comida-a-domicilio/<cat>` y `Search-Show?q=` renderizan **product
tiles**. Datos útiles por tile (`client._parse_products()`):

- `data-pid` — id de producto.
- `data-gtmdata` / `data-gtmga4data` — **JSON de analítica** con `name`,
  `category`, `price` (0.00 cuando no hay tienda o el producto es configurable).
  Es la vía más fiable para nombre y precio.
- `input[name="product-url"]` — slug del producto.
- `.product-tile__description-text` — descripción.

Categorías conocidas: `pizzas` (con subcategorías `las-clasicas`, `las-maestras`,
`las-brutales`, `crea-tu-pizza`, `infantil`, `sin-gluten`, …), `entrantes`,
`burgersymas`, `postres`, `bebidas`, más `ofertas`.

### Ficha / configurador (`Product-ShowQuickView`)

`GET ?pid=<pid>` (opcional `st=<storeId>`, `pliid` para editar una línea del
carrito). Devuelve el HTML del modal de producto. De ahí se extraen
(`client.product_details()`):

- **Tamaños**: `[data-select-variation][data-value-id]` → label (Individual /
  Mediana / Familiar) y `data-attr-value` (16 / 20 / 21).
- **Grupos de opciones** (`ul.pdp-option`, `data-attr-id`): bases/masas
  (`tpz_productBases`: Clásica, Fina, Masa Madre +1,00€, 3 Pisos +2,50€), bordes,
  salsas, ingredientes, con sus suplementos de precio en el texto.
- El botón `add-to-cart` expone el **pid con variante**:
  `data-product-id="<pid>-<talla>"` (p.ej. `999990000006814-mediana`) y la URL
  `Cart-AddProduct`.

### Variantes (SFCC "dwvar")

Internamente el tamaño es un atributo de variación:
`dwvar_<pid>_tpz_productSize=20`. Para el carrito basta el pid con sufijo de talla;
el resto de opciones (masa, ingredientes) se envían al configurar la línea.

---

## 5. Ofertas y promociones

- **`/ofertas`** usa **offer tiles** (`.offer-tile`), **no** product tiles. Cada
  tile lleva `data-promotion-id`, `data-name`, `data-detail`. → `client.offers()`.
- **`Offers-Details`** — `GET ?promotionID=<id>` (¡`promotionID`, no `pid`!).
  Devuelve el HTML del modal con las condiciones. Si la tienda está cerrada o la
  promo no aplica, responde "no cumple los requisitos / no disponible".
  → `client.offer_details()`.
- `Offers-SaveVoucherData` / `Offers-ShowWinWheel` — pertenecen a la **ruleta de
  premios** (win wheel), **no** a un cajetín de cupones genérico. Por eso el MCP
  **no** implementa `apply_voucher`.

---

## 6. Fidelización — MiTelepi

- **`Loyalty-Dashboard`** (`/mitelepi`) — "Mis promos": catálogo de **canjes**. Cada
  `.promo-card-item` lleva `data-promotion-id` (`LY…`), título, descripción, y en
  el footer el **coste combinado**: `precio€ + N Puntos`, más
  `data-tab-content` = canal (`delivery` / `takeaway`). → `client.loyalty_rewards()`.
- **`Loyalty-MyActivity`** — "Historial de puntos": tres `.point-card`
  (disponibles / pendientes / canjeados) y la lista de movimientos
  (`±N pts · fecha · descripción`, con caducidades). → `client.loyalty_status()`.
- **Canje**: no hay endpoint de "canjear ya"; con puntos suficientes la promo `LY…`
  aparece disponible en el flujo de ofertas/carrito y se materializa **al pedir**
  (máx. 3 canjes distintos por pedido). Como el MCP no hace checkout, el canje se
  remata en web/app.

---

## 7. Carrito y pedidos

| Controlador | Método | Uso |
|---|---|---|
| `Cart-MiniCartShow` | GET `?isToggleable&isCheckoutPage` | HTML del mini-carrito (líneas, total, dirección, URLs de borrado) |
| `Cart-AddProduct` | POST form `pid`,`quantity` | añadir línea (requiere tienda en sesión) |
| `Cart-RemoveProductLineItem` / `remove-offer` | GET (URL provista en el HTML del carrito) | quitar línea/oferta |
| `Order-Reorder` | POST form `orderID`,`historyPage=true` | rellenar carrito con un pedido pasado (requiere tienda) |
| `Order-History` | GET (`/secure/orderhistory`) | tarjetas de pedidos: `data-order-id`, fecha, artículos |
| `Order-Details` | GET `?orderID=<id>` | recibo: dirección, envío, pago, totales (**`orderID`** con D mayúscula; `orderId` da 410) |
| `Order-ToogleFavoriteOrder` | POST `?orderId=<id>` | marcar favorito (nótese el typo **Toogle** en el nombre real del endpoint) |

Notas:

- El **añadir al carrito** de la web es un simple `FormData{pid,quantity}` (visto en
  `productList.js`, handler `add_to_cart`).
- El **reorder** de la web usa `FormData{orderID,historyPage}` y **solo funciona con
  tienda seleccionada**; sin ella, la web lanza el flujo de selección de tienda
  (`startOrderInitWIthRedirect`). Igual en el MCP.
- **Borrado de líneas** (descubierto en vivo): cada línea se ancla en su
  `<input class="quantity">`, que lleva `data-uuid`, `data-pid` y
  `data-product-name`; el importe de línea está en
  `.line-item-total-price-amount.item-total-<uuid>`. Se elimina con
  `Cart-RemoveProductLineItem?pid=<pid>&uuid=<uuid>` (firma estándar SFRA; **no**
  hay una URL de borrado ya montada en el DOM para las líneas de producto — ese
  fue un bug inicial del MCP). Las **ofertas** sí traen `data-url` con
  `Cart-RemoveOffer?promotionID=…` o `?promotionGroupID=…` (esta última la usa
  `reorder`).
- **Checkout**: `CheckoutServices-*` / `CheckoutShippingServices-*` (SFRA estándar).
  **No** implementado ni documentado a fondo a propósito: pediría datos de pago y
  gastaría dinero.

---

## 8. Gotchas (resumen para depurar rápido)

1. **HTTP 410 en `Stores-SetStore`** → estás mandando formulario; manda **JSON**.
2. **Sin precios en la carta** → no hay tienda en sesión (o está **cerrada**);
   llama a `status`.
3. **`Order-Details` da 410** → usaste `orderId`; es **`orderID`**.
4. **`Offers-Details` da 410 / vacío** → usaste `pid`; es **`promotionID`**.
5. **CSRF inválido** → el token es de un solo uso; relee una página fresca.
6. **Nombre del endpoint de favoritos** → `Order-ToogleFavoriteOrder` (typo real,
   con doble 'o').
7. **`price: "0.00"`** en `data-gtmdata` → producto configurable o sin tienda; no es
   gratis.
8. **Geocodificación** → el sitio usa Google (key propia); el MCP usa Nominatim,
   que puede diferir ligeramente en coordenadas.

---

## 9. Inventario de endpoints usados por el MCP

```
Account-Login                Account-LoginMigratedCustomer
Stores-FindStores            Stores-GetStore              Stores-SetStore
Search-Show                  Product-ShowQuickView
Offers-Details
Loyalty-Dashboard            Loyalty-MyActivity
Cart-MiniCartShow            Cart-AddProduct
Order-History                Order-Details                Order-Reorder
Order-ToogleFavoriteOrder
```

Otros vistos en los bundles pero **no** usados (referencia para futuras
iteraciones): `Account-SubmitRegistration`, `Account-PasswordResetDialogForm`,
`Account-UpdateMigratedProfile`, `Address-*`, `Stores-GetStore`, `Stores-LogSearch`,
`Offers-SaveVoucherData`, `Offers-ShowWinWheel`, `Page-SetLocale`,
`DeliveryForm-Logger`, `Cart-RemoveProductLineItem`, `CheckoutServices-*`.

---

## 10. Cómo recapturar / verificar

Los parsers se prueban **offline** contra fixtures HTML **sanitizadas** (sin datos
personales) en [`tests/fixtures/`](../tests/fixtures/). Si Telepizza cambia el
frontal:

1. Captura el HTML real (logueado) del endpoint afectado.
2. **Sanitiza** nombre, dirección, CP, teléfono, email, nº de pedido, id de
   fidelización, coordenadas y tokens CSRF antes de guardarlo como fixture.
3. Ajusta el parser en `client.py` y corre `python -m pytest tests/ -q`.

> ⚠️ Nunca subas HTML crudo del sitio: contiene datos de la cuenta. Los volcados de
> trabajo viven en `.debug/`, ignorado por git.
