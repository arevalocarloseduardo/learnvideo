#!/usr/bin/env bash
# Genera un token de un año para el modo sesión (`claude setup-token`) y lo guarda en .env
# sin mostrarlo. Corrélo en una terminal, no con `!` en el chat: el token no tiene que quedar
# en la conversación. No hace falta reiniciar el servidor: el token se lee en cada llamada.
# Si ya corriste `claude setup-token` y copiaste el token: `bash scripts/guardar_token.sh --guardar`.
set -euo pipefail
cd "$(dirname "$0")/.."

# Que no herede la configuración de otra sesión de Claude (la app de escritorio define estas).
unset ANTHROPIC_BASE_URL ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN

# De dónde se lee lo copiado: macOS, Linux con Wayland o con X11. Si no hay ninguno, se pega a mano.
if command -v pbpaste >/dev/null; then pegar=(pbpaste); borrar=(pbcopy); tecla="⌘C"
elif command -v wl-paste >/dev/null; then pegar=(wl-paste); borrar=(wl-copy --clear); tecla="Ctrl+Shift+C"
elif command -v xclip >/dev/null; then pegar=(xclip -o -selection clipboard); borrar=(xclip -selection clipboard); tecla="Ctrl+Shift+C"
else pegar=(); borrar=(); tecla=""
fi

if [ "${1:-}" != "--guardar" ]; then
  claude setup-token
  echo
  if [ -n "$tecla" ]; then
    read -r -p "Seleccioná el token (empieza con sk-ant-oat), copialo con $tecla y tocá Enter… " _
  fi
fi

leer() {
  if [ ${#pegar[@]} -gt 0 ]; then
    "${pegar[@]}"
  else   # sin portapapeles: se pega en la terminal sin que se vea; si viene en dos renglones, se juntan
    echo "Pegá el token (no se va a ver) y tocá Enter dos veces:" >&2
    while IFS= read -rs renglon && [ -n "$renglon" ]; do printf '%s\n' "$renglon"; done
    echo >&2
  fi
}

# Si la terminal es angosta el token aparece partido en dos renglones: se juntan los pedazos
# hasta el primer renglón vacío o con espacios (el texto que sigue al token).
token=$(leer | awk '
  !empezo { i = index($0, "sk-ant-oat"); if (!i) next; empezo = 1; $0 = substr($0, i) }
  { sub(/^[[:space:]]+/, ""); sub(/[[:space:]]+$/, "") }
  ($0 == "" || /[[:space:]]/) && t != "" { exit }
  { t = t $0 }
  END { print t }' | grep -o '^sk-ant-oat[0-9A-Za-z_-]*' || true)

if [ ${#token} -lt 80 ]; then
  if grep -q '^CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat' .env 2>/dev/null; then
    echo "No hay un token para guardar, pero en .env ya hay uno. Si «Probar conexión» anda, no hace falta nada más."
  else
    echo "No encontré el token. Volvé a correr el script y copiá el token entero."
  fi
  exit 1
fi

touch .env
grep -v '^CLAUDE_CODE_OAUTH_TOKEN=' .env > .env.nuevo || true
printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$token" >> .env.nuevo
mv .env.nuevo .env
chmod 600 .env
if [ ${#borrar[@]} -gt 0 ]; then "${borrar[@]}" < /dev/null || true; fi
echo "Listo: el token quedó en .env. Tocá «Probar conexión» en learnvideo."
