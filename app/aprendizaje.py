"""Cómo aprende learnvideo.

Dos piezas que se alimentan de las mismas etiquetas:
1. Clasificador propio: regresión logística sobre las huellas de los clips ya etiquetados.
   Aprende de los ejemplos y da una probabilidad, pero no explica.
2. La IA: mira la hoja de cuadros del clip junto con los casos parecidos que el experto ya
   explicó y el manual de criterios, que se reescribe con cada tanda. Explica el porqué.

Para que el acierto sea honesto, cada clip se predice antes de que el experto lo vea, solo
con lo que se sabía al crear la tanda, y nunca con ejemplos del mismo video (misma vaca).
"""
import json
import random
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sklearn.linear_model import LogisticRegression

from . import config, db, ia

VARIANTES = {
    "ia_ensenada": "IA con ejemplos y explicaciones",
    "ia_sin_explicaciones": "IA con ejemplos, sin explicaciones",
    "ia_sola": "IA sin enseñarle nada",
    "clasificador": "Clasificador propio",
}
ESQUEMA_MANUAL = {
    "type": "object",
    "properties": {"manual": {"type": "string"}},
    "required": ["manual"],
    "additionalProperties": False,
}
_vectores: dict[str, np.ndarray] = {}


class FaltanDatos(ValueError):
    pass


# ---------- datos ----------

def _txt(texto: str) -> dict:
    return {"type": "text", "text": texto}


def _img(relativa: str) -> dict:
    return {"type": "image", "path": str(config.DATOS / relativa)}


def _vector(fila: dict) -> np.ndarray:
    ruta = fila["huella"]
    if ruta not in _vectores:
        _vectores[ruta] = np.load(config.DATOS / ruta)
    return _vectores[ruta]


def ejemplos(proyecto_id: int, antes_de: str | None = None) -> list[dict]:
    """Clips con etiqueta, con la explicación del experto y, si hubo, la corrección."""
    filas = db.filas(
        """SELECT c.id AS clip_id, c.video_id, c.hoja, c.huella, c.miniatura, v.canal,
                  e.respuesta, e.explicacion, e.origen, e.creado,
                  r.por_que AS nota_revision, p.respuesta AS dijo_ia
           FROM etiqueta e
           JOIN clip c ON c.id = e.clip_id
           JOIN video v ON v.id = c.video_id
           LEFT JOIN revision r ON r.clip_id = c.id
           LEFT JOIN prediccion p ON p.clip_id = c.id AND p.variante = 'ia_ensenada'
           WHERE v.proyecto_id = ? AND c.estado = 'listo' AND c.huella IS NOT NULL
           ORDER BY e.creado, e.clip_id""",
        (proyecto_id,),
    )
    return [f for f in filas if antes_de is None or f["creado"] <= antes_de]


def conteo(proyecto_id: int) -> dict:
    filas = db.filas(
        """SELECT e.respuesta, COUNT(*) AS n FROM etiqueta e JOIN clip c ON c.id = e.clip_id
           JOIN video v ON v.id = c.video_id WHERE v.proyecto_id = ? AND c.estado = 'listo' GROUP BY e.respuesta""",
        (proyecto_id,),
    )
    return {f["respuesta"]: f["n"] for f in filas}


# ---------- pieza 1: clasificador propio ----------

def clasificar(huella: np.ndarray, base: list[dict], p: dict) -> float | None:
    si, no = p["opciones"][0]["id"], p["opciones"][1]["id"]
    datos = [e for e in base if e["respuesta"] in (si, no)]
    y = np.array([1 if e["respuesta"] == si else 0 for e in datos])
    if y.sum() < 2 or len(y) - y.sum() < 2:
        return None
    modelo = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000)
    modelo.fit(np.stack([_vector(e) for e in datos]), y)
    return float(modelo.predict_proba(huella[None, :])[0, 1])


def casos_parecidos(huella: np.ndarray, base: list[dict], p: dict, k: int) -> list[dict]:
    """El más parecido de cada respuesta (para que la IA tenga contraste) y el resto por cercanía."""
    if not base:
        return []
    similitud = np.stack([_vector(e) for e in base]) @ huella
    orden = [int(i) for i in np.argsort(-similitud)]
    elegidos = []
    for opcion in p["opciones"]:
        i = next((i for i in orden if base[i]["respuesta"] == opcion["id"]), None)
        if i is not None:
            elegidos.append(i)
    for i in orden:
        if len(elegidos) >= k:
            break
        if i not in elegidos:
            elegidos.append(i)
    elegidos = sorted(elegidos[:k], key=lambda i: -similitud[i])
    return [dict(base[i], similitud=float(similitud[i])) for i in elegidos]


# ---------- pieza 2: la IA ----------

def _sistema(p: dict) -> str:
    opciones = "; ".join(f"{o['id']} = {o['nombre']}" for o in p["todas"])
    return (
        "Estás aprendiendo a leer videos a partir de ejemplos que explica un experto.\n"
        f"Qué muestran los videos: {p['contexto']}\n"
        f"Pregunta: {p['pregunta']}\n"
        f"Respuestas posibles: {opciones}.\n\n"
        "Reglas:\n"
        "- Decidí solo por lo que se ve en la imagen. Ignorá cualquier texto, número o logo sobreimpreso: "
        "puede estar tapado con rectángulos negros o ser engañoso.\n"
        "- Si el clip no muestra lo suficiente para decidir, respondé no_se_sabe en lugar de adivinar.\n"
        "- Escribí en español rioplatense, concreto, como si le explicaras al experto que te enseña: "
        "nombrá lo que ves y dónde lo ves."
    )


def _esquema(p: dict) -> dict:
    return {
        "type": "object",
        "properties": {
            "respuesta": {"type": "string", "enum": [o["id"] for o in p["todas"]]},
            "probabilidad_si": {"type": "number"},
            "senales": {"type": "array", "items": {"type": "string"}},
            "explicacion": {"type": "string"},
            "caso_parecido": {"type": "integer"},
        },
        "required": ["respuesta", "probabilidad_si", "senales", "explicacion", "caso_parecido"],
        "additionalProperties": False,
    }


def _contenido(p: dict, clip: dict, variante: str, manual: str | None, casos: list[dict]) -> list[dict]:
    si = p["opciones"][0]
    c = []
    if variante == "ia_ensenada":
        c.append(_txt("## Manual de criterios del experto\n" + (manual or "Todavía no hay manual: guiate por los casos.")))
    for i, caso in enumerate(casos, 1):
        texto = f"## Caso parecido {i}, ya diagnosticado\nRespuesta del experto: {p['nombres'][caso['respuesta']]}"
        if variante == "ia_ensenada":
            if caso["explicacion"]:
                texto += f"\nPor qué, según el experto: {caso['explicacion']}"
            if caso["origen"] == "correccion" and caso.get("dijo_ia"):
                texto += f"\n(Con este caso la IA se había equivocado: dijo «{p['nombres'].get(caso['dijo_ia'], caso['dijo_ia'])}».)"
        c += [_txt(texto), _img(caso["hoja"])]
    c.append(_txt(
        f"## Clip a evaluar\nSon {config.CUADROS_POR_CLIP} cuadros del mismo clip, en orden: "
        "de izquierda a derecha y de arriba abajo."
    ))
    c.append(_img(clip["hoja"]))
    c.append(_txt(
        "Respondé en el formato pedido:\n"
        f"- respuesta: {', '.join(o['id'] for o in p['todas'])}.\n"
        f"- probabilidad_si: de 0 a 1, qué tan probable es que la respuesta correcta sea «{si['nombre']}».\n"
        "- senales: lo que ves que sostiene tu respuesta, en frases cortas.\n"
        "- explicacion: de 2 a 4 oraciones para el experto.\n"
        "- caso_parecido: el número del caso parecido que más se le parece (0 si no hay casos o ninguno se parece)."
    ))
    return c


# ---------- manual de criterios ----------

def manual_actual(proyecto_id: int) -> dict | None:
    return db.fila("SELECT * FROM manual WHERE proyecto_id = ? ORDER BY version DESC LIMIT 1", (proyecto_id,))


def guardar_manual(proyecto_id: int, texto: str, origen: str, n_ejemplos: int) -> dict:
    actual = manual_actual(proyecto_id)
    version = (actual["version"] if actual else 0) + 1
    db.ejecutar(
        "INSERT INTO manual (proyecto_id, version, texto, origen, n_ejemplos) VALUES (?, ?, ?, ?, ?)",
        (proyecto_id, version, texto.strip(), origen, n_ejemplos),
    )
    return manual_actual(proyecto_id)


def reescribir_manual(proyecto_id: int, antes_de: str | None = None) -> dict:
    p = db.proyecto(proyecto_id)
    base = ejemplos(proyecto_id, antes_de)
    actual = manual_actual(proyecto_id)
    partes = ["## Manual actual\n" + (actual["texto"] if actual else "(todavía no hay)")]
    if actual and actual["origen"] == "editado":
        partes.append("El experto editó este manual a mano: respetá lo que escribió.")
    for opcion in p["todas"]:
        explicaciones = [
            e["explicacion"].strip() for e in base
            if e["respuesta"] == opcion["id"] and e["explicacion"].strip()
            and (e["origen"] == "ensenanza" or (e["origen"] == "confirmacion" and (e["nota_revision"] or "").strip()))
        ]
        if explicaciones:
            partes.append(f"## Explicaciones del experto para «{opcion['nombre']}»\n" + "\n".join(f"- {x}" for x in explicaciones[-40:]))
    correcciones = [e for e in base if e["origen"] == "correccion"]
    if correcciones:
        lineas = [
            f"- La IA dijo «{p['nombres'].get(e['dijo_ia'], e['dijo_ia'])}», era «{p['nombres'][e['respuesta']]}». "
            f"Por qué: {e['nota_revision'] or e['explicacion'] or '(sin explicación)'}"
            for e in correcciones[-30:]
        ]
        partes.append("## Correcciones del experto (la IA se equivocó)\n" + "\n".join(lineas))
    s, n = p["opciones"][0]["nombre"], p["opciones"][1]["nombre"]
    sistema = (
        f"Llevás el manual de criterios de un experto que le enseña a una IA a responder «{p['pregunta']}». "
        f"Qué muestran los videos: {p['contexto']}\n"
        "Tu trabajo: destilar sus explicaciones y correcciones en un manual corto y accionable, que después "
        "se usa para decidir clips nuevos.\n\nReglas:\n"
        "- Solo criterios que se ven en la imagen; nada de texto sobreimpreso ni datos de títulos.\n"
        "- Máximo 250 palabras, en español rioplatense, con viñetas que empiecen con «- ».\n"
        f"- Secciones, cada una con un título que empiece con «## »: Señales de {s}; Señales de {n}; "
        "Cuándo decir que no se puede saber; Errores que ya cometiste.\n"
        "- Si el experto se contradice, quedate con lo más reciente."
    )
    datos = ia.responder_json(sistema, [_txt("\n\n".join(partes))], ESQUEMA_MANUAL, para="manual")
    return guardar_manual(proyecto_id, datos["manual"], "automatico", len(base))


# ---------- enseñar y validar ----------

def etiquetar(clip_id: int, respuesta: str, explicacion: str):
    clip = db.fila("SELECT c.*, v.proyecto_id FROM clip c JOIN video v ON v.id = c.video_id WHERE c.id = ?", (clip_id,))
    if not clip:
        raise FaltanDatos("Ese clip no existe.")
    p = db.proyecto(clip["proyecto_id"])
    if respuesta not in p["nombres"]:
        raise FaltanDatos("Respuesta desconocida.")
    pendiente = db.fila(
        """SELECT 1 FROM prediccion pr WHERE pr.clip_id = ? AND pr.variante = 'ia_ensenada'
           AND pr.clip_id NOT IN (SELECT clip_id FROM revision)""",
        (clip_id,),
    )
    if pendiente:
        raise FaltanDatos("Ese clip está en una tanda: validalo desde «Validar».")
    db.ejecutar(
        "INSERT OR REPLACE INTO etiqueta (clip_id, respuesta, explicacion, origen) VALUES (?, ?, ?, 'ensenanza')",
        (clip_id, respuesta, explicacion.strip()),
    )


def siguiente_para_ensenar(proyecto_id: int) -> dict | None:
    """Primero la respuesta con menos ejemplos (según la pista del título), después variar de video."""
    p = db.proyecto(proyecto_id)
    c = conteo(proyecto_id)
    la_que_falta = min(p["opciones"], key=lambda o: c.get(o["id"], 0))["id"]
    return db.fila(
        """SELECT c.*, v.titulo, v.canal, v.pista, v.url, v.descripcion,
                  (SELECT COUNT(*) FROM etiqueta e JOIN clip c2 ON c2.id = e.clip_id WHERE c2.video_id = c.video_id) AS hechos_video
           FROM clip c JOIN video v ON v.id = c.video_id
           WHERE v.proyecto_id = ? AND c.estado = 'listo' AND c.huella IS NOT NULL
             AND c.id NOT IN (SELECT clip_id FROM etiqueta) AND c.id NOT IN (SELECT clip_id FROM prediccion)
           ORDER BY (v.pista = ?) DESC, hechos_video ASC, c.id ASC LIMIT 1""",
        (proyecto_id, la_que_falta),
    )


def crear_tanda(proyecto_id: int) -> int:
    p = db.proyecto(proyecto_id)
    abierta = db.fila("SELECT id FROM tanda WHERE proyecto_id = ? AND estado IN ('prediciendo', 'validando', 'error')", (proyecto_id,))
    if abierta:
        return abierta["id"]
    c = conteo(proyecto_id)
    faltan = [f"{config.MINIMO_POR_CLASE - c.get(o['id'], 0)} de «{o['nombre']}»"
              for o in p["opciones"] if c.get(o["id"], 0) < config.MINIMO_POR_CLASE]
    if faltan:
        raise FaltanDatos("Para predecir hace falta enseñarle al menos " + " y ".join(faltan) + ".")
    libres = db.filas(
        """SELECT c.id, c.video_id FROM clip c JOIN video v ON v.id = c.video_id
           WHERE v.proyecto_id = ? AND c.estado = 'listo' AND c.huella IS NOT NULL
             AND c.id NOT IN (SELECT clip_id FROM etiqueta) AND c.id NOT IN (SELECT clip_id FROM prediccion)""",
        (proyecto_id,),
    )
    if not libres:
        raise FaltanDatos("No quedan clips sin usar. Cargá más videos.")
    random.shuffle(libres)
    elegidos, videos = [], set()
    for clip in libres:                       # primero un clip por video, para variar
        if clip["video_id"] not in videos:
            elegidos.append(clip)
            videos.add(clip["video_id"])
    elegidos += [clip for clip in libres if clip not in elegidos]
    n = sum(c.get(o["id"], 0) for o in p["opciones"])
    with db.conexion() as con:
        tanda_id = con.execute("INSERT INTO tanda (proyecto_id, n_ejemplos) VALUES (?, ?)", (proyecto_id, n)).lastrowid
        for clip in elegidos[: config.TANDA]:
            for variante in ("ia_ensenada", "clasificador"):
                con.execute("INSERT INTO prediccion (clip_id, tanda_id, variante) VALUES (?, ?, ?)", (clip["id"], tanda_id, variante))
    return tanda_id


def correr_tanda(tanda_id: int):
    t = db.fila("SELECT * FROM tanda WHERE id = ?", (tanda_id,))
    db.ejecutar("UPDATE tanda SET estado = 'prediciendo', error = NULL WHERE id = ?", (tanda_id,))
    try:
        manual = manual_actual(t["proyecto_id"])
        if not manual or manual["n_ejemplos"] < len(ejemplos(t["proyecto_id"], t["creado"])):
            manual = reescribir_manual(t["proyecto_id"], t["creado"])
        db.ejecutar("UPDATE tanda SET manual_version = ? WHERE id = ?", (manual["version"], tanda_id))
    except Exception as e:  # sin manual no se predice: la tanda queda en error con el motivo a la vista
        db.ejecutar("UPDATE tanda SET estado = 'error', error = ? WHERE id = ?", (str(e) or type(e).__name__, tanda_id))
        return
    pendientes = [f["id"] for f in db.filas("SELECT id FROM prediccion WHERE tanda_id = ? AND respuesta IS NULL", (tanda_id,))]
    with ThreadPoolExecutor(max_workers=2) as grupo:
        list(grupo.map(_predecir_sin_romper, pendientes))
    fallidas = db.fila(
        "SELECT COUNT(*) AS n, MAX(error) AS error FROM prediccion WHERE tanda_id = ? AND variante = 'ia_ensenada' AND respuesta IS NULL",
        (tanda_id,),
    )
    if fallidas["n"]:
        db.ejecutar("UPDATE tanda SET estado = 'error', error = ? WHERE id = ?", (fallidas["error"], tanda_id))
    else:
        db.ejecutar("UPDATE tanda SET estado = 'validando', error = NULL WHERE id = ?", (tanda_id,))
        _cerrar_si_termino(tanda_id)


def _predecir_sin_romper(prediccion_id: int):
    try:
        predecir(prediccion_id)
    except (ia.ErrorIA, FaltanDatos) as e:
        db.ejecutar("UPDATE prediccion SET error = ? WHERE id = ?", (str(e), prediccion_id))
    except Exception as e:  # una respuesta rara de la IA no puede frenar el resto de la tanda
        db.ejecutar("UPDATE prediccion SET error = ? WHERE id = ?", (f"Error inesperado: {e}"[:300], prediccion_id))


def predecir(prediccion_id: int):
    pr = db.fila("SELECT * FROM prediccion WHERE id = ?", (prediccion_id,))
    t = db.fila("SELECT * FROM tanda WHERE id = ?", (pr["tanda_id"],))
    clip = db.fila("SELECT c.*, v.proyecto_id FROM clip c JOIN video v ON v.id = c.video_id WHERE c.id = ?", (pr["clip_id"],))
    p = db.proyecto(clip["proyecto_id"])
    base = [e for e in ejemplos(p["id"], t["creado"]) if e["video_id"] != clip["video_id"]]
    huella = _vector(clip)
    variante = pr["variante"]

    if variante == "clasificador":
        prob = clasificar(huella, base, p)
        if prob is None:
            raise FaltanDatos("Faltan ejemplos para el clasificador.")
        si, no = p["opciones"]
        ganadora = si if prob >= 0.5 else no
        _guardar(prediccion_id, ganadora["id"], prob,
                 f"Su huella se parece más a los ejemplos de «{ganadora['nombre']}».", [], [], "huellas DINOv2")
        return

    manual = None
    if variante == "ia_ensenada":
        m = db.fila("SELECT texto FROM manual WHERE proyecto_id = ? AND version = ?", (p["id"], t["manual_version"]))
        manual = m["texto"] if m else None
    casos = casos_parecidos(huella, base, p, config.VECINOS) if variante != "ia_sola" else []
    datos = ia.responder_json(_sistema(p), _contenido(p, clip, variante, manual, casos), _esquema(p), para=f"prediccion:{variante}")

    respuesta = datos.get("respuesta") if datos.get("respuesta") in p["nombres"] else "no_se_sabe"
    prob = min(max(float(datos.get("probabilidad_si") or 0.5), 0.0), 1.0)
    elegido = int(datos.get("caso_parecido") or 0)
    parecidos = [
        {"clip_id": caso["clip_id"], "respuesta": caso["respuesta"], "similitud": round(caso["similitud"], 3),
         "miniatura": caso["miniatura"], "elegido": i == elegido}
        for i, caso in enumerate(casos, 1)
    ]
    _guardar(prediccion_id, respuesta, prob, datos.get("explicacion", ""), datos.get("senales") or [], parecidos, config.MODELO)


def _guardar(prediccion_id, respuesta, prob, explicacion, senales, parecidos, modelo):
    db.ejecutar(
        """UPDATE prediccion SET respuesta = ?, prob_si = ?, explicacion = ?, senales = ?, vecinos = ?,
           modelo = ?, error = NULL WHERE id = ?""",
        (respuesta, prob, explicacion, json.dumps(senales, ensure_ascii=False), json.dumps(parecidos, ensure_ascii=False),
         modelo, prediccion_id),
    )


def reintentar_tanda(tanda_id: int):
    db.ejecutar("UPDATE prediccion SET error = NULL WHERE tanda_id = ? AND respuesta IS NULL", (tanda_id,))
    db.ejecutar("UPDATE tanda SET estado = 'prediciendo', error = NULL WHERE id = ?", (tanda_id,))


def revisar(clip_id: int, acerto: bool, respuesta_correcta: str | None, por_que: str):
    pr = db.fila("SELECT * FROM prediccion WHERE clip_id = ? AND variante = 'ia_ensenada'", (clip_id,))
    if not pr or pr["respuesta"] is None:
        raise FaltanDatos("Ese clip no tiene una predicción para validar.")
    p = db.proyecto(db.fila("SELECT proyecto_id FROM tanda WHERE id = ?", (pr["tanda_id"],))["proyecto_id"])
    correcta = pr["respuesta"] if acerto else respuesta_correcta
    if correcta not in p["nombres"]:
        raise FaltanDatos("Elegí cuál era la respuesta correcta.")
    if not acerto and correcta == pr["respuesta"]:
        raise FaltanDatos("Marcaste que se equivocó, pero elegiste la misma respuesta que dio la IA.")
    por_que = por_que.strip()
    with db.conexion() as con:
        con.execute(
            "INSERT OR REPLACE INTO revision (clip_id, tanda_id, acerto, respuesta_correcta, por_que) VALUES (?, ?, ?, ?, ?)",
            (clip_id, pr["tanda_id"], int(acerto), correcta, por_que),
        )
        explicacion = por_que if por_que else ("" if not acerto else pr["explicacion"] or "")
        con.execute(
            "INSERT OR REPLACE INTO etiqueta (clip_id, respuesta, explicacion, origen) VALUES (?, ?, ?, ?)",
            (clip_id, correcta, explicacion, "confirmacion" if acerto else "correccion"),
        )
    _cerrar_si_termino(pr["tanda_id"])


def _cerrar_si_termino(tanda_id: int):
    faltan = db.fila(
        """SELECT COUNT(*) AS n FROM prediccion WHERE tanda_id = ? AND variante = 'ia_ensenada'
           AND clip_id NOT IN (SELECT clip_id FROM revision)""",
        (tanda_id,),
    )["n"]
    if not faltan:
        db.ejecutar("UPDATE tanda SET estado = 'cerrada' WHERE id = ? AND estado = 'validando'", (tanda_id,))


def comparar(proyecto_id: int):
    """Corre las variantes de control sobre los clips ya validados, con lo que se sabía en cada tanda."""
    faltantes = []
    for variante in ("ia_sola", "ia_sin_explicaciones"):
        for f in db.filas(
            """SELECT r.clip_id, r.tanda_id FROM revision r JOIN tanda t ON t.id = r.tanda_id
               WHERE t.proyecto_id = ? AND r.clip_id NOT IN (SELECT clip_id FROM prediccion WHERE variante = ?)""",
            (proyecto_id, variante),
        ):
            faltantes.append(db.ejecutar(
                "INSERT INTO prediccion (clip_id, tanda_id, variante) VALUES (?, ?, ?)", (f["clip_id"], f["tanda_id"], variante)
            ))
    faltantes += [f["id"] for f in db.filas(
        """SELECT pr.id FROM prediccion pr JOIN tanda t ON t.id = pr.tanda_id
           WHERE t.proyecto_id = ? AND pr.variante IN ('ia_sola', 'ia_sin_explicaciones') AND pr.respuesta IS NULL""",
        (proyecto_id,),
    ) if f["id"] not in faltantes]
    with ThreadPoolExecutor(max_workers=2) as grupo:
        list(grupo.map(_predecir_sin_romper, faltantes))
