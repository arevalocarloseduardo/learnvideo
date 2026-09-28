"""SQLite: una conexión por operación (sirve igual desde el servidor y desde los hilos de fondo)."""
import json
import sqlite3
from contextlib import contextmanager

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS proyecto (
  id INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL,
  pregunta TEXT NOT NULL,
  contexto TEXT NOT NULL,            -- qué muestran los videos (va al prompt)
  opciones TEXT NOT NULL,            -- JSON [{"id","nombre"}]; la primera es el "sí"
  ejemplo TEXT NOT NULL DEFAULT '',  -- explicación de ejemplo que se muestra al enseñar
  gris INTEGER NOT NULL DEFAULT 0,   -- 1 = imágenes en blanco y negro (ecografías): se descartan los clips con color
  candidatos TEXT,                   -- archivo en data/ con videos sugeridos de YouTube
  activo INTEGER NOT NULL DEFAULT 0, -- el proyecto que se ve en la interfaz
  creado TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS video (
  id INTEGER PRIMARY KEY,
  proyecto_id INTEGER NOT NULL REFERENCES proyecto(id),
  url TEXT,
  origen_id TEXT,
  titulo TEXT, canal TEXT, descripcion TEXT,
  duracion REAL,
  archivo TEXT,
  pista TEXT,                        -- diagnóstico según el título: solo lo ve el humano
  estado TEXT NOT NULL DEFAULT 'en_cola',   -- en_cola | bajando | procesando | listo | error
  error TEXT,
  creado TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (proyecto_id, origen_id)
);
CREATE TABLE IF NOT EXISTS clip (
  id INTEGER PRIMARY KEY,
  video_id INTEGER NOT NULL REFERENCES video(id),
  inicio REAL NOT NULL,
  fin REAL NOT NULL,
  archivo TEXT, hoja TEXT, miniatura TEXT, huella TEXT,
  recorte TEXT,                      -- JSON: recorte, máscara y avisos
  estado TEXT NOT NULL DEFAULT 'listo',     -- listo | descartado
  creado TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS etiqueta (
  clip_id INTEGER PRIMARY KEY REFERENCES clip(id),
  respuesta TEXT NOT NULL,
  explicacion TEXT NOT NULL DEFAULT '',
  origen TEXT NOT NULL,              -- ensenanza | correccion | confirmacion
  creado TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tanda (
  id INTEGER PRIMARY KEY,
  proyecto_id INTEGER NOT NULL REFERENCES proyecto(id),
  n_ejemplos INTEGER NOT NULL,       -- etiquetas sí/no que había al predecir
  manual_version INTEGER,
  estado TEXT NOT NULL DEFAULT 'prediciendo',  -- prediciendo | validando | cerrada | error
  error TEXT,
  creado TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS prediccion (
  id INTEGER PRIMARY KEY,
  clip_id INTEGER NOT NULL REFERENCES clip(id),
  tanda_id INTEGER REFERENCES tanda(id),
  variante TEXT NOT NULL,            -- ia_ensenada | ia_sola | ia_sin_explicaciones | clasificador
  respuesta TEXT,
  prob_si REAL,
  explicacion TEXT,
  senales TEXT,                      -- JSON
  vecinos TEXT,                      -- JSON: clips parecidos que vio
  modelo TEXT,
  costo_usd REAL NOT NULL DEFAULT 0,
  error TEXT,
  creado TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (clip_id, variante)
);
CREATE TABLE IF NOT EXISTS revision (
  clip_id INTEGER PRIMARY KEY REFERENCES clip(id),
  tanda_id INTEGER REFERENCES tanda(id),
  acerto INTEGER NOT NULL,
  respuesta_correcta TEXT NOT NULL,
  por_que TEXT NOT NULL DEFAULT '',
  creado TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS manual (
  id INTEGER PRIMARY KEY,
  proyecto_id INTEGER NOT NULL REFERENCES proyecto(id),
  version INTEGER NOT NULL,
  texto TEXT NOT NULL,
  origen TEXT NOT NULL,              -- automatico | editado
  n_ejemplos INTEGER NOT NULL DEFAULT 0,
  creado TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS consumo (
  id INTEGER PRIMARY KEY,
  motor TEXT, modelo TEXT, para TEXT,
  tokens_entrada INTEGER, tokens_salida INTEGER,
  costo_usd REAL NOT NULL DEFAULT 0,
  creado TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS clip_video ON clip(video_id);
CREATE INDEX IF NOT EXISTS prediccion_tanda ON prediccion(tanda_id);
"""

PROYECTO_INICIAL = {
    "nombre": "Preñez bovina por ecografía",
    "pregunta": "¿Está preñada?",
    "contexto": (
        "Clips de ecografías transrectales de vacas (modo B, en escala de grises). "
        "El experto decide si la vaca está preñada o vacía mirando el útero."
    ),
    "opciones": [{"id": "prenada", "nombre": "Preñada"}, {"id": "vacia", "nombre": "Vacía"}],
    "ejemplo": "Ej.: arriba a la izquierda hay una bolsa negra de líquido y adentro se ve el embrión, con el latido.",
    "gris": 1,
    "candidatos": "candidatos.json",
}

# Columnas que se agregaron después: una base vieja las recibe al arrancar.
_COLUMNAS_NUEVAS = {
    "ejemplo": "TEXT NOT NULL DEFAULT ''",
    "gris": "INTEGER NOT NULL DEFAULT 0",
    "candidatos": "TEXT",
    "activo": "INTEGER NOT NULL DEFAULT 0",
}

NO_SE_SABE = {"id": "no_se_sabe", "nombre": "No se puede saber"}


@contextmanager
def conexion():
    con = sqlite3.connect(config.DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def inicializar():
    with conexion() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(ESQUEMA)
        columnas = {c["name"] for c in con.execute("PRAGMA table_info(proyecto)")}
        faltan = [c for c in _COLUMNAS_NUEVAS if c not in columnas]
        for c in faltan:
            con.execute(f"ALTER TABLE proyecto ADD COLUMN {c} {_COLUMNAS_NUEVAS[c]}")
        if faltan:  # la base es de antes de los proyectos: el único que había es el de ecografías
            p = PROYECTO_INICIAL
            con.execute("UPDATE proyecto SET ejemplo = ?, gris = ?, candidatos = ? WHERE nombre = ?",
                        (p["ejemplo"], p["gris"], p["candidatos"], p["nombre"]))
        if not con.execute("SELECT 1 FROM proyecto").fetchone():
            _insertar(con, **PROYECTO_INICIAL)
        if not con.execute("SELECT 1 FROM proyecto WHERE activo = 1").fetchone():
            con.execute("UPDATE proyecto SET activo = 1 WHERE id = (SELECT MIN(id) FROM proyecto)")


def _insertar(con, nombre, pregunta, contexto, opciones, ejemplo="", gris=0, candidatos=None) -> int:
    return con.execute(
        "INSERT INTO proyecto (nombre, pregunta, contexto, opciones, ejemplo, gris, candidatos) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (nombre, pregunta, contexto, json.dumps(opciones, ensure_ascii=False), ejemplo, int(gris), candidatos),
    ).lastrowid


def filas(sql, params=()):
    with conexion() as con:
        return [dict(f) for f in con.execute(sql, params).fetchall()]


def fila(sql, params=()):
    with conexion() as con:
        f = con.execute(sql, params).fetchone()
        return dict(f) if f else None


def ejecutar(sql, params=()):
    with conexion() as con:
        return con.execute(sql, params).lastrowid


def proyecto(proyecto_id=None):
    """El proyecto pedido o, sin id, el que está activo en la interfaz."""
    if proyecto_id is None:
        p = fila("SELECT * FROM proyecto ORDER BY activo DESC, id LIMIT 1")
    else:
        p = fila("SELECT * FROM proyecto WHERE id = ?", (proyecto_id,))
    p["opciones"] = json.loads(p["opciones"])
    p["todas"] = p["opciones"] + [NO_SE_SABE]
    p["nombres"] = {o["id"]: o["nombre"] for o in p["todas"]}
    return p


def crear_proyecto(**campos) -> int:
    with conexion() as con:
        return _insertar(con, **campos)


def activar(proyecto_id: int):
    ejecutar("UPDATE proyecto SET activo = (id = ?)", (proyecto_id,))


def proyectos() -> list[dict]:
    """Todos los proyectos, con lo que tiene cada uno."""
    lista = filas(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM video v WHERE v.proyecto_id = p.id) AS videos,
                  (SELECT COUNT(*) FROM clip c JOIN video v ON v.id = c.video_id
                    WHERE v.proyecto_id = p.id AND c.estado = 'listo') AS clips,
                  (SELECT COUNT(*) FROM etiqueta e JOIN clip c ON c.id = e.clip_id JOIN video v ON v.id = c.video_id
                    WHERE v.proyecto_id = p.id) AS ejemplos,
                  (SELECT COUNT(*) FROM tanda t WHERE t.proyecto_id = p.id AND t.estado = 'cerrada') AS tandas
           FROM proyecto p ORDER BY p.activo DESC, p.id"""
    )
    for p in lista:
        p["opciones"] = json.loads(p["opciones"])
    return lista
