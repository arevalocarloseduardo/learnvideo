"""Modo API: SDK oficial de Anthropic. Se activa solo con ANTHROPIC_API_KEY en .env.

Salida estructurada con output_config.format (JSON garantizado), fallbacks del servidor por
si el modelo rechaza un caso, y un tope de gasto propio (LEARNVIDEO_TOPE_USD).
"""
import base64
import json
import threading

import anthropic

from .. import config, db
from . import ErrorIA, IANoConectada, TopeAlcanzado

NOMBRE = "API de Anthropic"
PRECIOS = {  # dólares por millón de tokens: entrada, salida
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
CON_FALLBACKS = {"claude-opus-5", "claude-fable-5-1"}
_semaforo = threading.Semaphore(3)
_cliente = None


def _api():
    global _cliente
    if _cliente is None:
        _cliente = anthropic.Anthropic()
    return _cliente


def gastado() -> float:
    return db.fila("SELECT COALESCE(SUM(costo_usd), 0) AS total FROM consumo WHERE motor = 'api'")["total"]


def _bloques(contenido: list[dict]) -> list[dict]:
    salida = []
    for b in contenido:
        if b["type"] == "image":
            datos = base64.standard_b64encode(open(b["path"], "rb").read()).decode("utf-8")
            salida.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": datos}})
        else:
            salida.append({"type": "text", "text": b["text"]})
    return salida


def responder_json(sistema: str, contenido: list[dict], esquema: dict, para: str) -> dict:
    if gastado() >= config.TOPE_USD:
        raise TopeAlcanzado(f"Se llegó al tope de gasto de US${config.TOPE_USD:.0f}. Subilo en .env (LEARNVIDEO_TOPE_USD).")
    pedido = dict(
        model=config.MODELO,
        max_tokens=16000,
        system=sistema,
        messages=[{"role": "user", "content": _bloques(contenido)}],
        output_config={"format": {"type": "json_schema", "schema": esquema}},
    )
    if config.MODELO in CON_FALLBACKS:
        pedido.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    try:
        with _semaforo:
            r = _api().beta.messages.create(**pedido)
    except anthropic.AuthenticationError:
        raise IANoConectada("La ANTHROPIC_API_KEY de .env no es válida.")
    except anthropic.PermissionDeniedError:
        raise IANoConectada("La clave de API no tiene permiso para este modelo.")
    except anthropic.RateLimitError:
        raise ErrorIA("La API está limitando pedidos. Probá de nuevo en un minuto.")
    except anthropic.APIStatusError as e:
        raise ErrorIA(f"Error de la API ({e.status_code}): {e.message}"[:300])
    except anthropic.APIConnectionError:
        raise ErrorIA("No hay conexión con la API de Anthropic.")

    u = r.usage
    entrada = (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
    precio_in, precio_out = PRECIOS.get(config.MODELO, (5.0, 25.0))
    costo = entrada * precio_in / 1e6 + (u.output_tokens or 0) * precio_out / 1e6
    db.ejecutar(
        "INSERT INTO consumo (motor, modelo, para, tokens_entrada, tokens_salida, costo_usd) VALUES (?, ?, ?, ?, ?, ?)",
        ("api", config.MODELO, para, entrada, u.output_tokens or 0, costo),
    )

    if r.stop_reason == "refusal":
        raise ErrorIA("El modelo no quiso responder este caso.")
    texto = next((b.text for b in r.content if b.type == "text"), None)
    if not texto:
        raise ErrorIA("La API no devolvió texto.")
    return json.loads(texto)
