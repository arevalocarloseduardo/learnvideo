"""Motor de mentira para probar la interfaz sin gastar IA (LEARNVIDEO_IA=prueba).

No mira las imágenes: responde al azar pero siempre igual para el mismo clip. Nunca usarlo
para medir nada.
"""
import hashlib
import re

NOMBRE = "Motor de prueba (respuestas inventadas)"


def responder_json(sistema: str, contenido: list[dict], esquema: dict, para: str) -> dict:
    propiedades = esquema.get("properties", {})
    if "manual" in propiedades:
        texto = " ".join(b.get("text", "") for b in contenido if b["type"] == "text")
        explicaciones = re.findall(r"^- (.+)$", texto, flags=re.M)[:6]
        return {"manual": "## Señales que dio el experto\n" + "\n".join(f"- {e}" for e in explicaciones or ["(sin explicaciones)"])
                + "\n## Aviso\n- Manual inventado por el motor de prueba."}
    if "ok" in propiedades:
        return {"ok": True}
    imagenes = [b["path"] for b in contenido if b["type"] == "image"]
    semilla = int(hashlib.sha1((imagenes[-1] if imagenes else para).encode()).hexdigest(), 16)
    opciones = propiedades["respuesta"]["enum"]
    prob = (semilla % 100) / 100
    respuesta = opciones[0] if prob >= 0.5 else opciones[1]
    if 0.45 < prob < 0.55 and len(opciones) > 2:
        respuesta = opciones[2]
    casos = sum(1 for b in contenido if b["type"] == "text" and b["text"].startswith("## Caso parecido"))
    return {
        "respuesta": respuesta,
        "probabilidad_si": prob,
        "senales": ["respuesta inventada por el motor de prueba"],
        "explicacion": "Esta explicación es de relleno: el motor de prueba no mira la imagen. Sirve para ver cómo se ve la pantalla.",
        "caso_parecido": 1 if casos else 0,
    }
