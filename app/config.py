"""Rutas y parámetros de learnvideo. Todo lo configurable sale de .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

DATOS = Path(os.getenv("LEARNVIDEO_DATOS", RAIZ / "data"))
VIDEOS = DATOS / "videos"
CLIPS = DATOS / "clips"
HOJAS = DATOS / "hojas"
MINIATURAS = DATOS / "miniaturas"
HUELLAS = DATOS / "huellas"
DB = DATOS / "learnvideo.db"

for _carpeta in (VIDEOS, CLIPS, HOJAS, MINIATURAS, HUELLAS):
    _carpeta.mkdir(parents=True, exist_ok=True)

MODELO = os.getenv("LEARNVIDEO_MODELO", "claude-opus-5")
TOPE_USD = float(os.getenv("LEARNVIDEO_TOPE_USD", "20"))

# Cómo se cortan los videos en clips
CLIP_UNICO_HASTA = 25      # segundos: un video más corto queda como un solo clip
CLIP_LARGO = 12            # segundos de cada clip al cortar un video largo
CLIPS_POR_VIDEO = 8
CUADROS_POR_CLIP = 8       # cuadros que ve la IA de cada clip

# Aprendizaje
TANDA = 10                 # clips por tanda de predicción
VECINOS = 3                # casos parecidos que se le muestran a la IA
MINIMO_POR_CLASE = 5       # ejemplos de cada respuesta antes de poder predecir
