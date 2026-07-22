# VHS tape — demo ficticia del MCP de Telepizza con estética Claude Code.
#
# Render local:   vhs docs/demo/demo.tape      → docs/demo/demo.gif
# (VHS requiere ttyd y ffmpeg; en el repo lo genera GitHub Actions.)
#
# La salida es GUIONIZADA (datos inventados); no toca telepizza.es ni tu cuenta.

Output docs/demo/demo.gif

Require bash

Set Shell "bash"
Set FontSize 17
Set Width 1080
Set Height 780
Set Padding 30
Set TypingSpeed 42ms
Set Theme { "name": "claude-demo", "background": "#1b1b1d", "foreground": "#e6e6e6", "black": "#1b1b1d", "red": "#e6786f", "green": "#8fd18a", "yellow": "#e6c07b", "blue": "#79b8d6", "magenta": "#c39ac9", "cyan": "#7fc9c2", "white": "#e6e6e6", "brightBlack": "#7a7a7a", "brightRed": "#e6786f", "brightGreen": "#8fd18a", "brightYellow": "#e6c07b", "brightBlue": "#79b8d6", "brightMagenta": "#c39ac9", "brightCyan": "#7fc9c2", "brightWhite": "#ffffff", "cursor": "#e6a86b", "selection": "#33343a" }

# Arranca la TUI ficticia sin mostrar el comando
Hide
Type "bash docs/demo/claude-demo.sh"
Enter
Sleep 800ms
Show

# ── Turno 1: estado + ofertas ──
Sleep 700ms
Type "¿Está abierta mi Telepizza y qué ofertas hay hoy?"
Sleep 500ms
Enter
Sleep 4.5s

# ── Turno 2: alergia a frutos secos ──
Type "Soy alérgico a los frutos secos, ¿qué pizzas puedo pedir?"
Sleep 500ms
Enter
Sleep 5s

# ── Turno 3: puntos MiTelepi ──
Type "¿Cuántos puntos MiTelepi tengo y para qué me llegan?"
Sleep 500ms
Enter
Sleep 5s

Sleep 1.5s
