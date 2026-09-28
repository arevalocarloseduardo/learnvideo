"""Bajar videos, cortarlos en clips y preparar lo que ve la IA.

La IA nunca ve el video entero: ve una hoja con 8 cuadros de cada clip, recortada a la zona
que se mueve y con el texto fijo tapado, para que no pueda "leer" la respuesta si viene
escrita en pantalla. El humano, en cambio, ve el clip original con sonido. En los proyectos
en blanco y negro (ecografías) los cuadros van en gris y se descartan los clips con color.
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from . import config, db, huellas

ANCHO_COLOR = 320        # para medir si el clip tiene color alcanza con poca resolución
LADO_CUADRO = 448        # lado mayor de cada cuadro que ve la IA
CELDA_HOJA = 384         # cada cuadro entra en 384 × 384: con 4 columnas horizontales, 1554 px de ancho

FORMATO = (
    "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/"
    "bv*[height<=720]+ba/b[height<=720]/b"
)


def origen_de_url(url: str) -> str | None:
    """Id estable para no cargar dos veces el mismo video de YouTube."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    return f"Youtube-{m.group(1)}" if m else None


def bajar(url: str) -> dict:
    from yt_dlp import YoutubeDL

    opciones = {
        "format": FORMATO,
        "merge_output_format": "mp4",
        "outtmpl": str(config.VIDEOS / "%(extractor_key)s-%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    with YoutubeDL(opciones) as ydl:
        info = ydl.extract_info(url, download=True)
        descargas = info.get("requested_downloads") or []
        archivo = descargas[0]["filepath"] if descargas else ydl.prepare_filename(info)
    return {
        "archivo": archivo,
        "origen_id": f'{info.get("extractor_key", "Web")}-{info.get("id")}',
        "titulo": info.get("title"),
        "canal": info.get("channel") or info.get("uploader"),
        "descripcion": (info.get("description") or "")[:2000],
        "duracion": info.get("duration"),
    }


def sondear(archivo) -> dict:
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_format", "-of", "json", str(archivo)],
        capture_output=True, text=True, check=True,
    ).stdout
    datos = json.loads(salida)
    s = datos["streams"][0]
    ancho, alto = int(s["width"]), int(s["height"])
    rotacion = 0
    for extra in s.get("side_data_list") or []:
        if "rotation" in extra:
            rotacion = int(extra["rotation"])
    if abs(rotacion) % 180 == 90:          # videos de celular grabados en vertical
        ancho, alto = alto, ancho
    duracion = float(datos["format"].get("duration") or s.get("duration") or 0)
    return {"ancho": ancho, "alto": alto, "duracion": duracion}


def cortes(duracion: float) -> list[tuple[float, float]]:
    if duracion <= config.CLIP_UNICO_HASTA:
        return [(0.0, duracion)]
    margen = 2.0
    n = max(1, int((duracion - 2 * margen) // config.CLIP_LARGO))
    inicios = [margen + i * config.CLIP_LARGO for i in range(n)]
    if len(inicios) > config.CLIPS_POR_VIDEO:
        elegidos = np.linspace(0, len(inicios) - 1, config.CLIPS_POR_VIDEO).round().astype(int)
        inicios = [inicios[i] for i in elegidos]
    return [(s, min(s + config.CLIP_LARGO, duracion)) for s in inicios]


def _par(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _cuadros(archivo, inicio, fin, n, ancho, alto, recorte="", gris=True) -> np.ndarray:
    """n cuadros repartidos en [inicio, fin], como arreglo (n, alto, ancho[, 3])."""
    dur = max(fin - inicio, 0.2)
    vf = f"fps={n / dur:.5f}{recorte},scale={ancho}:{alto}:flags=area,format={'gray' if gris else 'rgb24'}"
    datos = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t", f"{dur:.3f}", "-i", str(archivo),
         "-vf", vf, "-frames:v", str(n), "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    forma = (alto, ancho) if gris else (alto, ancho, 3)
    tam = int(np.prod(forma))
    k = len(datos) // tam
    return np.frombuffer(datos[: k * tam], dtype=np.uint8).reshape((k, *forma))


def _fraccion_color(archivo, inicio, fin, ancho, alto) -> float:
    """Fracción de píxeles con color fuerte. Una ecografía en modo B es gris."""
    rgb = _cuadros(archivo, inicio, fin, 4, ancho, alto, gris=False).astype(np.float32) / 255
    if not len(rgb):
        return 0.0
    mayor, menor = rgb.max(axis=3), rgb.min(axis=3)
    saturacion = np.where(mayor > 0.08, (mayor - menor) / (mayor + 1e-6), 0)
    return float(np.mean(saturacion > 0.25))


def _filtro(mascara: np.ndarray, *pasos) -> np.ndarray:
    """Morfología con los filtros de rango de PIL: ("max", n) dilata, ("min", n) erosiona."""
    img = Image.fromarray((mascara * 255).astype(np.uint8))
    for tipo, n in pasos:
        img = img.filter(ImageFilter.MaxFilter(n) if tipo == "max" else ImageFilter.MinFilter(n))
    return np.array(img) > 0


def analizar(archivo, inicio, fin, ancho, alto, gris=True) -> dict:
    """Dónde está la imagen y qué tapar.

    Lo que se filma cambia de un cuadro a otro (en una ecografía, el moteado); los textos,
    escalas y logos sobreimpresos no. Con la varianza en el tiempo se encuentra el área viva de
    la imagen. El texto sobreimpreso nunca se oscurece (su mínimo en el tiempo es alto) mientras
    que el moteado sí: adentro del área viva se tapan solo esos trazos finos y fijos, afuera se
    tapa todo lo que sea claro y fijo.
    """
    a_ancho = min(ancho, 960)
    a_alto = _par(a_ancho * alto / ancho)
    g = _cuadros(archivo, inicio, fin, 24, a_ancho, a_alto).astype(np.float32)
    avisos = []
    if len(g) < 3:
        return {"caja": [0, 0, ancho, alto], "mascara": None, "avisos": ["clip demasiado corto"], "color": 0.0}

    k = 2 * round(a_ancho / 320) + 3                 # tamaño de los filtros según la resolución
    varianza, media, minimo = g.var(axis=0), g.mean(axis=0), g.min(axis=0)
    vivo = _filtro(varianza > 6.0, ("max", k), ("min", k), ("min", 3), ("max", 3))

    filas_vivas = np.where(vivo.mean(axis=1) > 0.04)[0]
    cols_vivas = np.where(vivo.mean(axis=0) > 0.04)[0]
    if vivo.mean() < 0.03 or not len(filas_vivas) or not len(cols_vivas):
        x0, y0, x1, y1 = 0, 0, a_ancho, a_alto
        avisos.append("imagen casi quieta: se usa el cuadro completo")
    else:
        aire = k
        x0, x1 = max(0, cols_vivas[0] - aire), min(a_ancho, cols_vivas[-1] + 1 + aire)
        y0, y1 = max(0, filas_vivas[0] - aire), min(a_alto, filas_vivas[-1] + 1 + aire)

    fijo = (minimo > 140) | ((varianza < 4.0) & (media > 110))
    fino = fijo & ~_filtro(fijo, ("min", k), ("max", k))        # lo que no sobrevive a la apertura: trazos finos
    cerca_de_lo_vivo = _filtro(vivo, ("max", k))
    tapar = _filtro((fino & cerca_de_lo_vivo) | (fijo & ~cerca_de_lo_vivo), ("max", 5))[y0:y1, x0:x1]
    mascara = None
    if 0 < tapar.mean() < 0.15:
        mascara = tapar
    elif tapar.mean() >= 0.15:
        avisos.append("mucho contenido fijo: no se tapó nada")

    color = 0.0
    if gris:   # en un proyecto en blanco y negro, un clip con color es otra cosa (una persona, un logo)
        color = _fraccion_color(archivo, inicio, fin, ANCHO_COLOR, _par(ANCHO_COLOR * alto / ancho))
        if color > 0.18:
            avisos.append("tiene mucho color para una imagen en blanco y negro")

    ex, ey = ancho / a_ancho, alto / a_alto
    caja = [int(x0 * ex), int(y0 * ey), int(x1 * ex), int(y1 * ey)]
    return {"caja": caja, "mascara": mascara, "avisos": avisos, "color": round(color, 3)}


def cuadros_ia(archivo, inicio, fin, caja, mascara, n, gris=True) -> list[Image.Image]:
    x0, y0, x1, y1 = caja
    w, h = x1 - x0, y1 - y0
    escala = LADO_CUADRO / max(w, h)
    ow, oh = _par(w * escala), _par(h * escala)
    g = _cuadros(archivo, inicio, fin, n, ow, oh, recorte=f",crop={w}:{h}:{x0}:{y0}", gris=gris)
    if mascara is not None and len(g):
        m = np.array(Image.fromarray((mascara * 255).astype(np.uint8)).resize((ow, oh), Image.NEAREST)) > 0
        g = g.copy()
        g[:, m] = 0
    return [Image.fromarray(c) for c in g]


def armar_hoja(cuadros: list[Image.Image], destino: Path):
    columnas = 4
    filas = (len(cuadros) + columnas - 1) // columnas
    w, h = cuadros[0].size
    if w >= h:
        cw, ch = CELDA_HOJA, _par(h * CELDA_HOJA / w)
    else:      # video vertical de celular: se achica el ancho y no se agranda la hoja
        cw, ch = _par(w * CELDA_HOJA / h), CELDA_HOJA
    separacion = 6
    modo = cuadros[0].mode
    lienzo = Image.new(modo, (columnas * cw + (columnas - 1) * separacion, filas * ch + (filas - 1) * separacion),
                       48 if modo == "L" else (48, 48, 48))
    for i, c in enumerate(cuadros):
        fila, col = divmod(i, columnas)
        lienzo.paste(c.resize((cw, ch), Image.LANCZOS), (col * (cw + separacion), fila * (ch + separacion)))
    lienzo.save(destino, quality=85)


def cortar_para_ver(archivo, inicio, fin, destino: Path):
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{inicio:.3f}", "-t", f"{fin - inicio:.3f}", "-i", str(archivo),
         "-vf", "scale='min(960,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(destino)],
        capture_output=True, check=True,
    )


def preparar_clip(video_id, archivo, inicio, fin, meta, gris=True) -> int | None:
    analisis = analizar(archivo, inicio, fin, meta["ancho"], meta["alto"], gris)
    cuadros = cuadros_ia(archivo, inicio, fin, analisis["caja"], analisis["mascara"], config.CUADROS_POR_CLIP, gris)
    if len(cuadros) < 2:
        return None
    clip_id = db.ejecutar("INSERT INTO clip (video_id, inicio, fin) VALUES (?, ?, ?)", (video_id, inicio, fin))
    nombre = f"{clip_id:05d}"
    armar_hoja(cuadros, config.HOJAS / f"{nombre}.jpg")
    mini = cuadros[len(cuadros) // 2].copy()
    mini.thumbnail((360, 360))
    mini.save(config.MINIATURAS / f"{nombre}.jpg", quality=82)
    cortar_para_ver(archivo, inicio, fin, config.CLIPS / f"{nombre}.mp4")
    np.save(config.HUELLAS / f"{nombre}.npy", huellas.huella(cuadros))

    recorte = {
        "caja": analisis["caja"],
        "tapado": analisis["mascara"] is not None,
        "avisos": analisis["avisos"],
        "color": analisis["color"],
    }
    estado = "descartado" if gris and analisis["color"] > 0.35 else "listo"   # claramente no es blanco y negro
    db.ejecutar(
        "UPDATE clip SET archivo=?, hoja=?, miniatura=?, huella=?, recorte=?, estado=? WHERE id=?",
        (f"clips/{nombre}.mp4", f"hojas/{nombre}.jpg", f"miniaturas/{nombre}.jpg", f"huellas/{nombre}.npy",
         json.dumps(recorte, ensure_ascii=False), estado, clip_id),
    )
    return clip_id


def _limpiar_clips_sin_uso(video_id):
    """Si un procesamiento quedó a medias, se rehace desde cero (sin tocar lo ya etiquetado)."""
    for c in db.filas(
        """SELECT * FROM clip WHERE video_id = ?
           AND id NOT IN (SELECT clip_id FROM etiqueta) AND id NOT IN (SELECT clip_id FROM prediccion)""",
        (video_id,),
    ):
        for campo in ("archivo", "hoja", "miniatura", "huella"):
            if c[campo]:
                (config.DATOS / c[campo]).unlink(missing_ok=True)
        db.ejecutar("DELETE FROM clip WHERE id = ?", (c["id"],))


def procesar_video(video_id: int):
    v = db.fila("SELECT * FROM video WHERE id = ?", (video_id,))
    if not v:
        return
    gris = bool(db.proyecto(v["proyecto_id"])["gris"])
    try:
        if not v["archivo"] or not Path(v["archivo"]).exists():
            db.ejecutar("UPDATE video SET estado = 'bajando', error = NULL WHERE id = ?", (video_id,))
            info = bajar(v["url"])
            repetido = db.fila(
                "SELECT id FROM video WHERE proyecto_id = ? AND origen_id = ? AND id != ?",
                (v["proyecto_id"], info["origen_id"], video_id),
            )
            if repetido:
                db.ejecutar("UPDATE video SET estado = 'error', error = 'Ese video ya estaba cargado' WHERE id = ?", (video_id,))
                return
            db.ejecutar(
                """UPDATE video SET archivo = ?, origen_id = ?, titulo = COALESCE(titulo, ?), canal = COALESCE(canal, ?),
                   descripcion = ?, duracion = ? WHERE id = ?""",
                (info["archivo"], info["origen_id"], info["titulo"], info["canal"], info["descripcion"], info["duracion"], video_id),
            )
            v = db.fila("SELECT * FROM video WHERE id = ?", (video_id,))

        db.ejecutar("UPDATE video SET estado = 'procesando' WHERE id = ?", (video_id,))
        meta = sondear(v["archivo"])
        db.ejecutar("UPDATE video SET duracion = ? WHERE id = ?", (meta["duracion"], video_id))
        _limpiar_clips_sin_uso(video_id)
        ya_hechos = {(round(c["inicio"], 1)) for c in db.filas("SELECT inicio FROM clip WHERE video_id = ?", (video_id,))}
        fallas = []
        for inicio, fin in cortes(meta["duracion"]):
            if round(inicio, 1) in ya_hechos:
                continue
            try:
                preparar_clip(video_id, v["archivo"], inicio, fin, meta, gris)
            except Exception as e:  # se saltea ese tramo y se sigue con los demás
                fallas.append(_mensaje(e))
        hechos = db.fila("SELECT COUNT(*) AS n FROM clip WHERE video_id = ?", (video_id,))["n"]
        if not hechos:
            raise RuntimeError(fallas[0] if fallas else "No salió ningún clip de este video.")
        db.ejecutar("UPDATE video SET estado = 'listo', error = ? WHERE id = ?",
                    (f"{len(fallas)} tramos no se pudieron procesar" if fallas else None, video_id))
    except Exception as e:  # el error queda a la vista en la pantalla de carga
        db.ejecutar("UPDATE video SET estado = 'error', error = ? WHERE id = ?", (_mensaje(e), video_id))


def _mensaje(e: Exception) -> str:
    """ffmpeg y yt-dlp explican al final; las excepciones de Python, al principio."""
    if isinstance(e, subprocess.CalledProcessError) and e.stderr:
        texto = e.stderr.decode(errors="ignore") if isinstance(e.stderr, bytes) else e.stderr
        lineas = [l for l in texto.splitlines() if l.strip()]
        return (lineas[-1] if lineas else str(e))[:300]
    lineas = [l for l in str(e).splitlines() if l.strip()]
    return (lineas[0] if lineas else type(e).__name__)[:300]
