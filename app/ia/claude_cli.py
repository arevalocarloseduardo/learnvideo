"""Modo sesión: el `claude` oficial en modo sin pantalla (`claude -p`) con el login de tu cuenta.

Las imágenes viajan como bloques base64 por la entrada stream-json (tiene que ser un pipe:
con la entrada redirigida desde un archivo, el CLI no lee nada). Se corre con un entorno
limpio y en una carpeta vacía para que no herede variables ni CLAUDE.md de nadie.
"""
import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading

from dotenv import dotenv_values

from .. import config, db
from . import ErrorIA, IANoConectada

NOMBRE = "Sesión de Claude Code"
_semaforo = threading.Semaphore(2)


_VARIABLES = ("HOME", "USER", "LOGNAME", "LANG", "TMPDIR",
              "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "TEMP", "TMP", "PATHEXT", "COMSPEC")


def _entorno() -> dict:
    env = {k: os.environ[k] for k in _VARIABLES if k in os.environ}
    # el PATH de la persona más los lugares donde suele instalarse `claude` (instalador oficial, Homebrew, npm)
    lugares = os.environ.get("PATH", "").split(os.pathsep) + [
        os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.claude/local"),
        "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
    ]
    env["PATH"] = os.pathsep.join(dict.fromkeys(l for l in lugares if l))
    # Token de `scripts/guardar_token.sh`: se lee de .env en cada llamada, así no hay que reiniciar.
    token = dotenv_values(config.RAIZ / ".env").get("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def _bloques(contenido: list[dict]) -> list[dict]:
    salida = []
    for b in contenido:
        if b["type"] == "image":
            datos = base64.standard_b64encode(open(b["path"], "rb").read()).decode()
            salida.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": datos}})
        else:
            salida.append({"type": "text", "text": b["text"]})
    return salida


def _json_de_texto(texto: str) -> dict:
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        raise ErrorIA("La IA no devolvió JSON.")
    return json.loads(texto[inicio : fin + 1])


def responder_json(sistema: str, contenido: list[dict], esquema: dict, para: str) -> dict:
    env = _entorno()
    claude = shutil.which("claude", path=env["PATH"])
    if not claude:
        raise IANoConectada("No encontré el comando `claude`. Instalá Claude Code o poné ANTHROPIC_API_KEY en .env.")
    mensaje = {"type": "user", "message": {"role": "user", "content": _bloques(contenido)}}
    comando = [
        claude, "-p",
        "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--system-prompt", sistema,
        "--tools", "",
        "--no-session-persistence", "--strict-mcp-config",
        "--setting-sources", "project",
        "--model", config.MODELO,
        "--json-schema", json.dumps(esquema),
    ]
    with _semaforo, tempfile.TemporaryDirectory() as carpeta:
        try:
            proc = subprocess.run(
                comando, input=json.dumps(mensaje) + "\n", capture_output=True, text=True,
                timeout=300, env=env, cwd=carpeta,
            )
        except subprocess.TimeoutExpired:
            raise ErrorIA("La IA tardó más de 5 minutos en responder.")

    resultado = None
    for linea in proc.stdout.splitlines():
        try:
            evento = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if evento.get("type") == "result":
            resultado = evento
    if resultado is None:
        detalle = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["sin salida"]
        raise ErrorIA(f"`claude` no devolvió respuesta: {detalle[0][:200]}")
    if resultado.get("is_error"):
        if resultado.get("api_error_status") == 401:
            raise IANoConectada("El login de Claude Code venció o lo revocaron. Corré `bash scripts/guardar_token.sh` en una terminal.")
        raise ErrorIA((resultado.get("result") or "La IA devolvió un error.")[:300])

    datos = resultado.get("structured_output")
    if not isinstance(datos, dict):
        datos = _json_de_texto(resultado.get("result") or "")

    uso = resultado.get("usage") or {}
    entrada = sum(uso.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    db.ejecutar(
        "INSERT INTO consumo (motor, modelo, para, tokens_entrada, tokens_salida, costo_usd) VALUES (?, ?, ?, ?, ?, 0)",
        ("sesion", config.MODELO, para, entrada, uso.get("output_tokens") or 0),
    )
    return datos
