"""Huella numérica de cada clip, hecha con DINOv2 (un modelo de visión ya entrenado).

Dos clips que se ven parecidos tienen huellas cercanas: sobre eso se entrena el clasificador
propio y se buscan los casos parecidos que se le muestran a la IA.
"""
import threading

import numpy as np
from PIL import Image

MODELO = "facebook/dinov2-small"
LADO = 224
MEDIA = np.array([0.485, 0.456, 0.406], dtype=np.float32)
DESVIO = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_candado = threading.Lock()
_cargado = None


def _cargar():
    global _cargado
    with _candado:
        if _cargado is None:
            import torch
            from transformers import AutoModel

            modelo = AutoModel.from_pretrained(MODELO).eval()
            dispositivo = "mps" if torch.backends.mps.is_available() else "cpu"
            _cargado = (modelo.to(dispositivo), dispositivo, torch)
    return _cargado


def _preparar(imagen: Image.Image) -> np.ndarray:
    """Rellena a cuadrado con negro (no recorta los bordes del abanico) y normaliza como ImageNet."""
    imagen = imagen.convert("RGB")
    lado = max(imagen.size)
    cuadrado = Image.new("RGB", (lado, lado), (0, 0, 0))
    cuadrado.paste(imagen, ((lado - imagen.width) // 2, (lado - imagen.height) // 2))
    x = np.asarray(cuadrado.resize((LADO, LADO), Image.BICUBIC), dtype=np.float32) / 255.0
    return ((x - MEDIA) / DESVIO).transpose(2, 0, 1)


def huella(imagenes) -> np.ndarray:
    """Promedio de los cuadros: token de clase + promedio de parches, normalizado."""
    global _cargado
    modelo, dispositivo, torch = _cargar()
    lote = torch.from_numpy(np.stack([_preparar(im) for im in imagenes]))
    with _candado, torch.no_grad():
        try:
            estados = modelo(pixel_values=lote.to(dispositivo)).last_hidden_state
        except RuntimeError:
            if dispositivo == "cpu":
                raise
            modelo, dispositivo = modelo.to("cpu"), "cpu"        # si el chip gráfico falla, se sigue con la CPU
            _cargado = (modelo, dispositivo, torch)
            estados = modelo(pixel_values=lote).last_hidden_state
        vector = torch.cat([estados[:, 0], estados[:, 1:].mean(dim=1)], dim=1).mean(dim=0)
    v = vector.float().cpu().numpy()
    return v / (np.linalg.norm(v) + 1e-8)
