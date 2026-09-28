"""Hilos de fondo: uno procesa videos (bajar, cortar, huellas) y otro habla con la IA."""
import queue
import threading
import traceback

from . import aprendizaje, db, ingesta

_videos: queue.Queue = queue.Queue()
_ia: queue.Queue = queue.Queue()
_en_curso = {"ia": None}


def encolar_video(video_id: int):
    _videos.put(video_id)


def encolar_tanda(tanda_id: int):
    _ia.put(("tanda", tanda_id))


def encolar_comparacion(proyecto_id: int):
    _ia.put(("comparar", proyecto_id))


def encolar_manual(proyecto_id: int):
    _ia.put(("manual", proyecto_id))


def ocupado_ia() -> str | None:
    return _en_curso["ia"]


def _bucle_videos():
    while True:
        video_id = _videos.get()
        try:
            ingesta.procesar_video(video_id)
        except Exception:
            traceback.print_exc()


def _bucle_ia():
    while True:
        tarea, ident = _ia.get()
        _en_curso["ia"] = tarea
        try:
            if tarea == "tanda":
                aprendizaje.correr_tanda(ident)
            elif tarea == "comparar":
                aprendizaje.comparar(ident)
            elif tarea == "manual":
                aprendizaje.reescribir_manual(ident)
        except Exception:
            traceback.print_exc()
        finally:
            _en_curso["ia"] = None


def arrancar():
    """Retoma lo que quedó a medias si el servidor se reinició."""
    for v in db.filas("SELECT id FROM video WHERE estado IN ('en_cola', 'bajando', 'procesando') ORDER BY id"):
        _videos.put(v["id"])
    for t in db.filas("SELECT id FROM tanda WHERE estado = 'prediciendo' ORDER BY id"):
        _ia.put(("tanda", t["id"]))
    threading.Thread(target=_bucle_videos, daemon=True, name="videos").start()
    threading.Thread(target=_bucle_ia, daemon=True, name="ia").start()
