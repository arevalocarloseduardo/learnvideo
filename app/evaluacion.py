"""Qué tan bien le va. Todo sale de clips que se predijeron antes de que el experto los viera."""
from . import db
from .aprendizaje import VARIANTES


def _metricas(filas: list[dict], si: str, no: str) -> dict:
    n = len(filas)
    aciertos = sum(f["respuesta"] == f["respuesta_correcta"] for f in filas)
    por_clase = {}
    for clase in (si, no):
        de_clase = [f for f in filas if f["respuesta_correcta"] == clase]
        por_clase[clase] = {"n": len(de_clase), "acierto": sum(f["respuesta"] == clase for f in de_clase) / len(de_clase) if de_clase else None}
    valores = [v["acierto"] for v in por_clase.values() if v["acierto"] is not None]
    return {
        "n": n,
        "aciertos": aciertos,
        "acierto": aciertos / n if n else None,
        "balanceado": sum(valores) / len(valores) if valores else None,
        "por_clase": por_clase,
        "abstencion": sum(f["respuesta"] == "no_se_sabe" for f in filas) / n if n else None,
    }


def _curva(filas: list[dict]) -> list[dict]:
    tandas = {}
    for f in filas:
        tandas.setdefault(f["tanda_id"], {"tanda": f["tanda_id"], "n_ejemplos": f["n_ejemplos"], "n": 0, "aciertos": 0})
        tandas[f["tanda_id"]]["n"] += 1
        tandas[f["tanda_id"]]["aciertos"] += int(f["respuesta"] == f["respuesta_correcta"])
    puntos, total, bien = [], 0, 0
    for t in sorted(tandas.values(), key=lambda x: x["tanda"]):
        total, bien = total + t["n"], bien + t["aciertos"]
        puntos.append(t | {"acierto": t["aciertos"] / t["n"], "acumulado": bien / total})
    return puntos


def resumen(proyecto_id: int) -> dict:
    p = db.proyecto(proyecto_id)
    si, no = p["opciones"][0]["id"], p["opciones"][1]["id"]
    filas = db.filas(
        """SELECT pr.clip_id, pr.variante, pr.respuesta, pr.prob_si, pr.explicacion, pr.tanda_id,
                  t.n_ejemplos, t.creado AS tanda_creada, r.respuesta_correcta, r.por_que, v.canal, c.miniatura
           FROM prediccion pr
           JOIN revision r ON r.clip_id = pr.clip_id
           JOIN tanda t ON t.id = pr.tanda_id
           JOIN clip c ON c.id = pr.clip_id
           JOIN video v ON v.id = c.video_id
           WHERE t.proyecto_id = ? AND pr.respuesta IS NOT NULL
           ORDER BY pr.tanda_id, pr.clip_id""",
        (proyecto_id,),
    )
    etiquetas = db.filas(
        """SELECT e.creado, v.canal FROM etiqueta e JOIN clip c ON c.id = e.clip_id
           JOIN video v ON v.id = c.video_id WHERE v.proyecto_id = ?""",
        (proyecto_id,),
    )
    for f in filas:
        f["canal_conocido"] = any(e["canal"] == f["canal"] and e["creado"] < f["tanda_creada"] for e in etiquetas)

    variantes = {}
    for clave, nombre in VARIANTES.items():
        de_variante = [f for f in filas if f["variante"] == clave]
        if de_variante:
            variantes[clave] = {"nombre": nombre, "curva": _curva(de_variante), **_metricas(de_variante, si, no)}

    # Comparación justa: solo los clips que tienen todas las variantes calculadas
    presentes = list(variantes)
    comunes = None
    for clave in presentes:
        ids = {f["clip_id"] for f in filas if f["variante"] == clave}
        comunes = ids if comunes is None else comunes & ids
    comparacion = {
        clave: _metricas([f for f in filas if f["variante"] == clave and f["clip_id"] in (comunes or set())], si, no)
        for clave in presentes
    } if len(presentes) > 1 else {}

    ensenada = [f for f in filas if f["variante"] == "ia_ensenada"]
    orden = [o["id"] for o in p["todas"]]
    matriz = {real: {dijo: sum(1 for f in ensenada if f["respuesta_correcta"] == real and f["respuesta"] == dijo) for dijo in orden} for real in orden}
    canales = {
        clave: {
            "conocido": _metricas([f for f in filas if f["variante"] == clave and f["canal_conocido"]], si, no),
            "nuevo": _metricas([f for f in filas if f["variante"] == clave and not f["canal_conocido"]], si, no),
        }
        for clave in ("ia_ensenada", "clasificador") if clave in variantes
    }
    errores = [f for f in ensenada if f["respuesta"] != f["respuesta_correcta"]]
    return {
        "variantes": variantes,
        "comparacion": comparacion,
        "n_comunes": len(comunes or ()),
        "matriz": matriz,
        "orden": orden,
        "canales": canales,
        "errores": errores[-30:][::-1],
        "hay_datos": bool(ensenada),
    }
