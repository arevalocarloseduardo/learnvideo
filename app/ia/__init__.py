"""Motor de IA intercambiable.

- Si hay ANTHROPIC_API_KEY en .env: API de Anthropic (SDK oficial), con tope de gasto.
- Si no: sesión de Claude Code (`claude -p`) con el login de tu cuenta. Sirve para probar en
  tu máquina; cuando lo usen otras personas tiene que ir por la API.

El contenido se arma con bloques {"type": "text", "text": ...} o {"type": "image", "path": ...}.
"""
import os
import time


class ErrorIA(RuntimeError):
    pass


class IANoConectada(ErrorIA):
    pass


class TopeAlcanzado(ErrorIA):
    pass


def motor():
    if os.getenv("LEARNVIDEO_IA") == "prueba":
        from . import prueba
        return prueba
    if os.getenv("ANTHROPIC_API_KEY"):
        from . import anthropic_api
        return anthropic_api
    from . import claude_cli
    return claude_cli


_ultima_prueba = {"cuando": 0.0, "resultado": None}


def responder_json(sistema: str, contenido: list[dict], esquema: dict, para: str) -> dict:
    """Cada llamada real también actualiza el estado del motor que se ve en la interfaz."""
    try:
        datos = motor().responder_json(sistema, contenido, esquema, para)
    except IANoConectada as e:
        _ultima_prueba.update(cuando=time.time(), resultado={"ok": False, "detalle": str(e)})
        raise
    _ultima_prueba.update(cuando=time.time(), resultado={"ok": True, "detalle": ""})
    return datos


def estado_guardado() -> dict:
    """El último resultado conocido, sin gastar una llamada."""
    return {"motor": motor().NOMBRE, **(_ultima_prueba["resultado"] or {"ok": None, "detalle": "Sin probar todavía"})}


def estado(forzar: bool = False) -> dict:
    """Qué motor se usa y si responde. La prueba real se cachea 10 minutos."""
    m = motor()
    if forzar or time.time() - _ultima_prueba["cuando"] > 600:
        try:
            m.responder_json(
                "Respondé exactamente lo que te piden.",
                [{"type": "text", "text": "Devolvé ok = true."}],
                {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False},
                para="prueba",
            )
            _ultima_prueba["resultado"] = {"ok": True, "detalle": ""}
        except ErrorIA as e:
            _ultima_prueba["resultado"] = {"ok": False, "detalle": str(e)}
        _ultima_prueba["cuando"] = time.time()
    return {"motor": m.NOMBRE, **_ultima_prueba["resultado"]}
