"""Servidor web de learnvideo: páginas + una API chica que usa el JavaScript de cada pantalla."""
import hashlib
import json
import re
import unicodedata
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import aprendizaje, config, db, evaluacion, ia, ingesta, trabajador

CARPETA = Path(__file__).parent


@asynccontextmanager
async def ciclo(_app):
    db.inicializar()
    trabajador.arrancar()
    yield


app = FastAPI(title="learnvideo", lifespan=ciclo, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=CARPETA / "static"), name="static")
for _sub in ("clips", "hojas", "miniaturas"):
    app.mount(f"/media/{_sub}", StaticFiles(directory=config.DATOS / _sub), name=_sub)
plantillas = Jinja2Templates(directory=CARPETA / "templates")


# ---------- filtros de plantilla ----------

def _pct(x, decimales=0):
    return "—" if x is None else f"{x * 100:.{decimales}f}%"


def _md(texto: str) -> Markup:
    """Markdown mínimo para el manual: títulos, viñetas, párrafos y **negritas**."""
    html, en_lista = [], False
    for linea in (texto or "").splitlines():
        l = linea.strip()
        if l.startswith(("- ", "* ", "• ")):
            if not en_lista:
                html.append("<ul>")
                en_lista = True
            html.append(f"<li>{_negritas(l[2:])}</li>")
            continue
        if en_lista:
            html.append("</ul>")
            en_lista = False
        if l.startswith("#"):
            html.append(f"<h3>{_negritas(l.lstrip('#').strip())}</h3>")
        elif l:
            html.append(f"<p>{_negritas(l)}</p>")
    if en_lista:
        html.append("</ul>")
    return Markup("\n".join(html))


def _negritas(texto: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", str(escape(texto)))


def _tiempo(segundos) -> str:
    s = int(segundos or 0)
    return f"{s // 60}:{s % 60:02d}"


def _estatico(ruta: str) -> str:
    """URL con la fecha del archivo, para que el navegador no use una versión vieja."""
    archivo = CARPETA / "static" / ruta
    return f"/static/{ruta}?v={int(archivo.stat().st_mtime) if archivo.exists() else 0}"


plantillas.env.globals["estatico"] = _estatico
plantillas.env.filters.update(pct=_pct, md=_md, tiempo=_tiempo, cargar_json=lambda s: json.loads(s) if s else [])


def _pagina(request: Request, nombre: str, activo: str, codigo: int = 200, **extra):
    return plantillas.TemplateResponse(
        request, nombre, {"p": db.proyecto(), "activo": activo, "ia": ia.estado_guardado(), "config": config, **extra},
        status_code=codigo,
    )


def _error(mensaje: str, codigo: int = 400):
    return JSONResponse({"ok": False, "error": mensaje}, status_code=codigo)


# ---------- consultas compartidas ----------

def _tanda_abierta(proyecto_id: int):
    t = db.fila(
        "SELECT * FROM tanda WHERE proyecto_id = ? AND estado IN ('prediciendo', 'validando', 'error') ORDER BY id DESC LIMIT 1",
        (proyecto_id,),
    )
    if t:
        t.update(db.fila(
            """SELECT COUNT(*) AS total,
                      SUM(respuesta IS NOT NULL) AS listas,
                      SUM(error IS NOT NULL) AS fallidas,
                      SUM(clip_id IN (SELECT clip_id FROM revision)) AS validadas
               FROM prediccion WHERE tanda_id = ? AND variante = 'ia_ensenada'""",
            (t["id"],),
        ))
    return t


def _clips_libres(proyecto_id: int) -> int:
    return db.fila(
        """SELECT COUNT(*) AS n FROM clip c JOIN video v ON v.id = c.video_id
           WHERE v.proyecto_id = ? AND c.estado = 'listo' AND c.huella IS NOT NULL
             AND c.id NOT IN (SELECT clip_id FROM etiqueta) AND c.id NOT IN (SELECT clip_id FROM prediccion)""",
        (proyecto_id,),
    )["n"]


def _progreso(p: dict) -> dict:
    c = aprendizaje.conteo(p["id"])
    faltan = {o["id"]: max(0, config.MINIMO_POR_CLASE - c.get(o["id"], 0)) for o in p["opciones"]}
    return {"conteo": c, "faltan": faltan, "listo": not any(faltan.values()), "total": sum(c.values())}


def _siguiente_paso(p: dict) -> dict:
    videos = db.fila(
        """SELECT COUNT(*) AS total, SUM(estado IN ('en_cola', 'bajando', 'procesando')) AS en_proceso
           FROM video WHERE proyecto_id = ?""",
        (p["id"],),
    )
    progreso = _progreso(p)
    tanda = _tanda_abierta(p["id"])
    libres = _clips_libres(p["id"])
    if not videos["total"]:
        return {"texto": "Cargá los primeros videos.", "boton": "Cargar videos", "url": "/cargar"}
    if tanda and tanda["estado"] == "error":
        return {"texto": f"La tanda {tanda['id']} se frenó: {tanda['error']}", "boton": "Ver la tanda", "url": "/validar"}
    if tanda and (tanda["listas"] or 0) > (tanda["validadas"] or 0):
        quedan = tanda["total"] - (tanda["validadas"] or 0)
        return {"texto": f"La IA ya predijo. Quedan {quedan} clips por validar en la tanda {tanda['id']}.", "boton": "Validar", "url": "/validar"}
    if tanda:
        return {"texto": f"La IA está mirando los clips de la tanda {tanda['id']}.", "boton": "Ver la tanda", "url": "/validar"}
    if not progreso["listo"]:
        faltan = " y ".join(f"{n} de «{p['nombres'][k]}»" for k, n in progreso["faltan"].items() if n)
        if not libres:
            return {"texto": f"Faltan {faltan} para poder predecir, y no quedan clips libres.", "boton": "Cargar más videos", "url": "/cargar"}
        return {"texto": f"Enseñale con ejemplos: faltan {faltan} para poder predecir.", "boton": "Enseñar", "url": "/ensenar"}
    if libres:
        return {"texto": f"Ya puede predecir. Hay {libres} clips que la IA no vio.", "boton": "Predecir una tanda", "url": "/validar"}
    if videos["en_proceso"]:
        return {"texto": "Se están procesando videos nuevos.", "boton": "Ver la carga", "url": "/cargar"}
    return {"texto": "No quedan clips sin usar.", "boton": "Cargar más videos", "url": "/cargar"}


# ---------- páginas ----------

@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    p = db.proyecto()
    numeros = db.fila(
        """SELECT (SELECT COUNT(*) FROM video WHERE proyecto_id = ?) AS videos,
                  (SELECT COUNT(*) FROM clip c JOIN video v ON v.id = c.video_id WHERE v.proyecto_id = ? AND c.estado = 'listo') AS clips,
                  (SELECT COUNT(*) FROM tanda WHERE proyecto_id = ? AND estado = 'cerrada') AS tandas""",
        (p["id"], p["id"], p["id"]),
    )
    resumen = evaluacion.resumen(p["id"])
    return _pagina(request, "inicio.html", "inicio", numeros=numeros, progreso=_progreso(p),
                   paso=_siguiente_paso(p), resumen=resumen, libres=_clips_libres(p["id"]))


def _candidatos(p: dict) -> list[dict]:
    """Videos sugeridos de YouTube para el proyecto, con la respuesta que sugiere el título."""
    archivo = config.DATOS / p["candidatos"] if p["candidatos"] else None
    return json.loads(archivo.read_text()) if archivo and archivo.exists() else []


def _lista_candidatos(p: dict) -> list[dict]:
    cargados = {f["origen_id"] for f in db.filas("SELECT origen_id FROM video WHERE proyecto_id = ?", (p["id"],))}
    return [c for c in _candidatos(p) if c["origen_id"] not in cargados]


def _cola(p: dict) -> list[dict]:
    return db.filas(
        """SELECT v.*, (SELECT COUNT(*) FROM clip c WHERE c.video_id = v.id AND c.estado = 'listo') AS clips,
                  (SELECT COUNT(*) FROM clip c WHERE c.video_id = v.id AND c.estado = 'descartado') AS descartados
           FROM video v WHERE v.proyecto_id = ? ORDER BY v.id DESC""",
        (p["id"],),
    )


@app.get("/cargar", response_class=HTMLResponse)
def cargar(request: Request):
    p = db.proyecto()
    candidatos = _lista_candidatos(p)
    grupos = [(o["id"], f"«{o['nombre']}» según el título", [c for c in candidatos if c["pista"] == o["id"]]) for o in p["opciones"]]
    grupos.append(("mixto", "Muestran las dos", [c for c in candidatos if c["pista"] == "mixto"]))
    grupos = [g for g in grupos if g[2]]
    # si una respuesta tiene menos de la mitad de videos que la otra, conviene traerlos todos
    por_respuesta = sorted((len(lista), clave) for clave, _, lista in grupos if clave != "mixto")
    escasa = por_respuesta[0][1] if len(por_respuesta) == 2 and por_respuesta[0][0] * 2 < por_respuesta[1][0] else None
    return _pagina(request, "cargar.html", "cargar", videos=_cola(p), grupos=grupos, escasa=escasa)


@app.get("/cargar/cola", response_class=HTMLResponse)
def cargar_cola(request: Request):
    p = db.proyecto()
    return plantillas.TemplateResponse(request, "_cola.html", {"videos": _cola(p), "p": p})


@app.get("/ensenar", response_class=HTMLResponse)
def ensenar(request: Request, clip: int | None = None):
    p = db.proyecto()
    if clip:
        actual = db.fila(
            """SELECT c.*, v.titulo, v.canal, v.pista, v.url, v.descripcion, e.respuesta AS etiqueta, e.explicacion AS etiqueta_explicacion
               FROM clip c JOIN video v ON v.id = c.video_id LEFT JOIN etiqueta e ON e.clip_id = c.id
               WHERE c.id = ? AND (e.origen IS NULL OR e.origen = 'ensenanza')
                 AND c.id NOT IN (SELECT clip_id FROM prediccion)""",
            (clip,),
        )
    else:
        actual = aprendizaje.siguiente_para_ensenar(p["id"])
    recientes = db.filas(
        """SELECT c.id, c.miniatura, e.respuesta FROM etiqueta e JOIN clip c ON c.id = e.clip_id
           JOIN video v ON v.id = c.video_id WHERE v.proyecto_id = ? AND e.origen = 'ensenanza'
           ORDER BY e.creado DESC, e.clip_id DESC LIMIT 8""",
        (p["id"],),
    )
    en_proceso = db.fila("SELECT COUNT(*) AS n FROM video WHERE proyecto_id = ? AND estado IN ('en_cola', 'bajando', 'procesando')", (p["id"],))["n"]
    return _pagina(request, "ensenar.html", "ensenar", clip=actual, recientes=recientes, progreso=_progreso(p), en_proceso=en_proceso)


@app.get("/validar", response_class=HTMLResponse)
def validar(request: Request):
    p = db.proyecto()
    tanda = _tanda_abierta(p["id"])
    item = None
    if tanda:
        item = db.fila(
            """SELECT pr.*, c.archivo, c.hoja, c.miniatura, c.inicio, c.fin, c.recorte,
                      v.titulo, v.canal, v.pista, v.url, v.descripcion
               FROM prediccion pr JOIN clip c ON c.id = pr.clip_id JOIN video v ON v.id = c.video_id
               WHERE pr.tanda_id = ? AND pr.variante = 'ia_ensenada' AND pr.respuesta IS NOT NULL
                 AND pr.clip_id NOT IN (SELECT clip_id FROM revision)
               ORDER BY ABS(pr.prob_si - 0.5) ASC, pr.id ASC LIMIT 1""",
            (tanda["id"],),
        )
        if item:
            item["clasificador"] = db.fila("SELECT * FROM prediccion WHERE clip_id = ? AND variante = 'clasificador'", (item["clip_id"],))
    cerradas = db.filas(
        """SELECT t.id, t.n_ejemplos, t.creado, COUNT(r.clip_id) AS n, SUM(r.acerto) AS aciertos
           FROM tanda t LEFT JOIN revision r ON r.tanda_id = t.id
           WHERE t.proyecto_id = ? AND t.estado = 'cerrada' GROUP BY t.id ORDER BY t.id DESC LIMIT 6""",
        (p["id"],),
    )
    return _pagina(request, "validar.html", "validar", tanda=tanda, item=item, progreso=_progreso(p),
                   libres=_clips_libres(p["id"]), cerradas=cerradas)


@app.get("/criterios", response_class=HTMLResponse)
def criterios(request: Request):
    p = db.proyecto()
    versiones = db.filas("SELECT * FROM manual WHERE proyecto_id = ? ORDER BY version DESC", (p["id"],))
    return _pagina(request, "criterios.html", "criterios", versiones=versiones,
                   n_ejemplos=len(aprendizaje.ejemplos(p["id"])), ocupado=trabajador.ocupado_ia())


@app.get("/proyectos", response_class=HTMLResponse)
def ver_proyectos(request: Request):
    return _pagina(request, "proyectos.html", "proyectos", proyectos=db.proyectos())


@app.get("/resultados", response_class=HTMLResponse)
def resultados(request: Request):
    p = db.proyecto()
    resumen = evaluacion.resumen(p["id"])
    curva = {clave: v["curva"] for clave, v in resumen["variantes"].items() if clave in ("ia_ensenada", "clasificador")}
    return _pagina(request, "resultados.html", "resultados", r=resumen, curva=curva, ocupado=trabajador.ocupado_ia())


# ---------- API ----------

@app.get("/api/ia/estado")
def api_estado_ia(probar: bool = False):
    return ia.estado(forzar=True) if probar else ia.estado_guardado()


def _agregar_video(p, url=None, archivo=None, titulo=None, canal=None, pista=None, origen_id=None) -> bool:
    if origen_id and db.fila("SELECT 1 FROM video WHERE proyecto_id = ? AND origen_id = ?", (p["id"], origen_id)):
        return False
    video_id = db.ejecutar(
        "INSERT INTO video (proyecto_id, url, archivo, titulo, canal, pista, origen_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (p["id"], url, archivo, titulo, canal, pista, origen_id),
    )
    trabajador.encolar_video(video_id)
    return True


@app.post("/api/videos")
async def api_videos(request: Request):
    p = db.proyecto()
    datos = await request.json()
    urls = re.findall(r"https?://\S+", datos.get("enlaces", ""))
    if not urls:
        return _error("No encontré ningún link. Pegá uno por línea, empezando con https://")
    pistas = {c["origen_id"]: c for c in _candidatos(p)}
    agregados = 0
    for url in urls:
        origen = ingesta.origen_de_url(url)
        c = pistas.get(origen, {})
        agregados += _agregar_video(p, url=url, origen_id=origen, titulo=c.get("titulo"), canal=c.get("canal"), pista=c.get("pista"))
    return {"ok": True, "agregados": agregados, "repetidos": len(urls) - agregados}


def _intercalar(candidatos: list[dict]) -> list[dict]:
    """Alterna las respuestas (y primero los videos cortos) para que haya clips de las dos desde el principio."""
    grupos: dict[str, list[dict]] = {}
    for c in sorted(candidatos, key=lambda c: c.get("duracion") or 0):
        grupos.setdefault(c["pista"], []).append(c)
    orden = []
    while any(grupos.values()):
        orden += [g.pop(0) for g in grupos.values() if g]
    return orden


@app.post("/api/candidatos")
async def api_candidatos(request: Request):
    p = db.proyecto()
    ids = set((await request.json()).get("ids", []))
    agregados = 0
    for c in _intercalar([c for c in _lista_candidatos(p) if c["origen_id"] in ids]):
        agregados += _agregar_video(p, url=c["url"], origen_id=c["origen_id"], titulo=c["titulo"], canal=c["canal"], pista=c["pista"])
    return {"ok": True, "agregados": agregados}


@app.post("/api/subir")
async def api_subir(archivos: list[UploadFile] = File(...)):
    p = db.proyecto()
    agregados = 0
    for archivo in archivos:
        extension = Path(archivo.filename or "").suffix.lower() or ".mp4"
        destino = config.VIDEOS / f"subido-{uuid.uuid4().hex[:12]}{extension}"
        resumen = hashlib.sha1()
        with destino.open("wb") as salida:
            while bloque := await archivo.read(1 << 20):
                resumen.update(bloque)
                salida.write(bloque)
        if not _agregar_video(p, archivo=str(destino), titulo=archivo.filename, canal="Subido por vos",
                              origen_id=f"archivo-{resumen.hexdigest()[:16]}"):
            destino.unlink(missing_ok=True)
        else:
            agregados += 1
    return {"ok": True, "agregados": agregados, "repetidos": len(archivos) - agregados}


@app.post("/api/videos/{video_id}/reintentar")
def api_reintentar_video(video_id: int):
    db.ejecutar("UPDATE video SET estado = 'en_cola', error = NULL WHERE id = ?", (video_id,))
    trabajador.encolar_video(video_id)
    return {"ok": True}


def _clave(nombre: str) -> str:
    """«Camina normal» → camina_normal: la clave con la que se guarda cada respuesta."""
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")[:40]


@app.post("/api/proyectos")
async def api_crear_proyecto(request: Request):
    datos = await request.json()
    campos = {k: " ".join(str(datos.get(k, "")).split()) for k in ("nombre", "pregunta", "si", "no", "ejemplo")}
    contexto = str(datos.get("contexto", "")).strip()
    faltan = [rotulo for k, rotulo in (("nombre", "el nombre"), ("pregunta", "la pregunta"), ("si", "la respuesta del sí"),
                                       ("no", "la respuesta del no")) if not campos[k]]
    if not contexto:
        faltan.append("qué muestran los videos")
    if faltan:
        lista = faltan[0] if len(faltan) == 1 else ", ".join(faltan[:-1]) + " y " + faltan[-1]
        return _error(("Falta " if len(faltan) == 1 else "Faltan ") + lista + ".")
    si, no = _clave(campos["si"]), _clave(campos["no"])
    if not si or not no or si == no:
        return _error("Las dos respuestas tienen que ser distintas.")
    if db.NO_SE_SABE["id"] in (si, no):
        return _error("«No se puede saber» ya viene incluida: poné las dos respuestas de sí y de no.")
    if db.fila("SELECT 1 FROM proyecto WHERE nombre = ?", (campos["nombre"],)):
        return _error("Ya hay un proyecto con ese nombre.")
    proyecto_id = db.crear_proyecto(
        nombre=campos["nombre"], pregunta=campos["pregunta"], contexto=contexto,
        opciones=[{"id": si, "nombre": campos["si"]}, {"id": no, "nombre": campos["no"]}],
        ejemplo=campos["ejemplo"], gris=bool(datos.get("gris")),
    )
    db.activar(proyecto_id)
    return {"ok": True, "proyecto_id": proyecto_id}


@app.post("/api/proyectos/{proyecto_id}/activar")
def api_activar_proyecto(proyecto_id: int):
    if not db.fila("SELECT 1 FROM proyecto WHERE id = ?", (proyecto_id,)):
        return _error("Ese proyecto no existe.", 404)
    db.activar(proyecto_id)
    return {"ok": True}


@app.post("/api/etiquetas")
async def api_etiquetas(request: Request):
    datos = await request.json()
    try:
        aprendizaje.etiquetar(int(datos["clip_id"]), datos.get("respuesta", ""), datos.get("explicacion", ""))
    except aprendizaje.FaltanDatos as e:
        return _error(str(e))
    return {"ok": True}


@app.post("/api/clips/{clip_id}/descartar")
def api_descartar(clip_id: int):
    usado = db.fila("SELECT 1 FROM prediccion WHERE clip_id = ? UNION SELECT 1 FROM etiqueta WHERE clip_id = ?", (clip_id, clip_id))
    if usado:
        return _error("Ese clip ya está etiquetado o en una tanda.")
    db.ejecutar("UPDATE clip SET estado = 'descartado' WHERE id = ?", (clip_id,))
    return {"ok": True}


@app.post("/api/tandas")
def api_tandas():
    p = db.proyecto()
    try:
        tanda_id = aprendizaje.crear_tanda(p["id"])
    except aprendizaje.FaltanDatos as e:
        return _error(str(e))
    t = db.fila("SELECT estado FROM tanda WHERE id = ?", (tanda_id,))
    if t["estado"] == "prediciendo":
        trabajador.encolar_tanda(tanda_id)
    return {"ok": True, "tanda_id": tanda_id}


@app.post("/api/tandas/{tanda_id}/reintentar")
def api_reintentar_tanda(tanda_id: int):
    aprendizaje.reintentar_tanda(tanda_id)
    trabajador.encolar_tanda(tanda_id)
    return {"ok": True}


@app.get("/api/tandas/actual")
def api_tanda_actual():
    t = _tanda_abierta(db.proyecto()["id"])
    return {"tanda": t}


@app.post("/api/revisiones")
async def api_revisiones(request: Request):
    datos = await request.json()
    try:
        aprendizaje.revisar(int(datos["clip_id"]), bool(datos.get("acerto")), datos.get("respuesta_correcta"), datos.get("por_que", ""))
    except aprendizaje.FaltanDatos as e:
        return _error(str(e))
    return {"ok": True}


@app.post("/api/manual")
async def api_manual(request: Request):
    p = db.proyecto()
    texto = (await request.json()).get("texto", "").strip()
    if not texto:
        return _error("El manual no puede quedar vacío.")
    aprendizaje.guardar_manual(p["id"], texto, "editado", len(aprendizaje.ejemplos(p["id"])))
    return {"ok": True}


@app.post("/api/manual/reescribir")
def api_reescribir():
    p = db.proyecto()
    if not aprendizaje.ejemplos(p["id"]):
        return _error("Todavía no hay ejemplos: enseñale algunos clips primero.")
    trabajador.encolar_manual(p["id"])
    return {"ok": True}


@app.post("/api/comparar")
def api_comparar():
    p = db.proyecto()
    if not db.fila("SELECT 1 FROM revision r JOIN tanda t ON t.id = r.tanda_id WHERE t.proyecto_id = ? LIMIT 1", (p["id"],)):
        return _error("Primero validá al menos una tanda.")
    trabajador.encolar_comparacion(p["id"])
    return {"ok": True}


@app.get("/api/ocupado")
def api_ocupado():
    p = db.proyecto()
    manual = aprendizaje.manual_actual(p["id"])
    return {"ia": trabajador.ocupado_ia(), "manual_version": manual["version"] if manual else 0}


@app.exception_handler(StarletteHTTPException)
async def no_encontrado(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith(("/api", "/media", "/static")):
        return _pagina(request, "404.html", "", codigo=404)
    return JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code)
