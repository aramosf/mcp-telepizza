#!/usr/bin/env bash
# TUI ficticia estilo Claude Code para la animación VHS (docs/demo/demo.tape).
#
# NO llama al MCP real ni a telepizza.es: imprime una conversación GUIONIZADA
# con datos INVENTADOS. Lee una línea por turno (la que teclea VHS) y responde.
set -u

E=$'\e'
R="$E[0m"
DIM="$E[38;5;244m"
ACCENT="$E[38;5;215m"   # tan/naranja tipo Claude
FG="$E[38;5;253m"
GREEN="$E[38;5;114m"
WARN="$E[38;5;222m"

banner() {
  printf '\n  %s◆%s %sClaude Code%s  %s·  telepizza MCP%s\n' "$ACCENT" "$R" "$FG" "$R" "$DIM" "$R"
  printf '  %s────────────────────────────────%s\n\n' "$DIM" "$R"
}

# Spinner breve con braille (glifos presentes en JetBrains Mono / DejaVu).
spin() {
  local label="$1"
  local frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
  local i=0
  while [ $i -lt 12 ]; do
    printf '\r  %s%s%s %s%s…%s   ' "$ACCENT" "${frames[$((i%10))]}" "$R" "$DIM" "$label" "$R"
    sleep 0.10
    i=$((i+1))
  done
  printf '\r%s\r' "$E[K"
}

tool() { # $1 llamada  $2 resultado
  printf '  %s●%s %s%s%s\n' "$GREEN" "$R" "$FG" "$1" "$R"
  sleep 0.25
  printf '     %s└─ %s%s\n' "$DIM" "$2" "$R"
  sleep 0.35
}

prompt() { # dibuja el prompt y espera la línea que teclea VHS
  printf '  %s>%s ' "$ACCENT" "$R"
  read -r _ || true
  echo
}

banner
sleep 0.5

# ─────────────────────────── Turno 1 ───────────────────────────
prompt
spin "Consultando estado y ofertas"
tool "status()" 'tienda "Villapizza" · abierta hasta 23:30'
tool "get_offers()" "22 ofertas"
printf '  %sSí, tu tienda está abierta hasta las 23:30 🍕  Ofertas de hoy:%s\n\n' "$FG" "$R"
printf '    • 2 medianas (2 ing.) ......... 8,95 € c/u\n'
printf '    • 3 medianas (2 ing.) ......... 7,95 € c/u\n'
printf '    • Familiar + entrante + bebida  15,95 €\n'
printf '    • Pizza Loca con masa madre ... +1 €\n\n'
sleep 1.2

# ─────────────────────────── Turno 2 ───────────────────────────
prompt
spin "Revisando ingredientes de la carta"
tool "get_menu(\"pizzas\")" "12 productos"
tool "get_product_details(…)" "ingredientes · masas · bordes"
printf '  %sNinguna pizza de la carta clásica lleva frutos secos en sus%s\n' "$FG" "$R"
printf '  %singredientes base. Serían seguras, entre otras:%s\n\n' "$FG" "$R"
printf '    %s✓%s Pepperoni     %s✓%s Barbacoa\n' "$GREEN" "$R" "$GREEN" "$R"
printf '    %s✓%s Carbonara     %s✓%s 4 Quesos\n' "$GREEN" "$R" "$GREEN" "$R"
printf '    %s✓%s Hawaiana      %s✓%s Vegetal\n\n' "$GREEN" "$R" "$GREEN" "$R"
printf '  %s▲ Evita toppings/borde "x Cheetos" y postres (posibles trazas).%s\n' "$WARN" "$R"
printf '  %s▲ Confírmalo con la tabla oficial de alérgenos antes de pedir.%s\n\n' "$WARN" "$R"
sleep 1.4

# ─────────────────────────── Turno 3 ───────────────────────────
prompt
spin "Consultando fidelización"
tool "get_loyalty_status()" "4.300 disponibles · 900 pendientes"
tool "get_loyalty_rewards()" "47 canjes"
printf '  %sTienes 4.300 puntos disponibles. Te llega, por ejemplo, para:%s\n\n' "$FG" "$R"
printf '    • Mediana 5 ingredientes ...... 1.600 pts + 9,95 €\n'
printf '    • Mediana con Masa Madre ...... 1.700 pts + 10,95 €\n\n'
printf '  %s▲ 1.200 puntos te caducan el 30/09 — buen momento para usarlos.%s\n\n' "$WARN" "$R"
sleep 1.6
