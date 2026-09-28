"""Arma la lista de videos sugeridos de YouTube para un proyecto de prueba y crea el proyecto.

Cada receta es un tema con muchos videos en YouTube: las búsquedas, cómo leer en el título qué
respuesta muestra el video (la «pista») y la pregunta del proyecto. Solo lee metadatos de
búsqueda: no baja videos. La pista la ve el humano que etiqueta; la IA nunca la ve.

    uv run python scripts/candidatos.py --receta perros --activar       # busca y deja el proyecto en uso
    uv run python scripts/candidatos.py --receta prenez --desde X.jsonl  # reusa una búsqueda guardada
"""
import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app import config, db  # noqa: E402

# ---------- preñez bovina por ecografía ----------

VACA = re.compile(r"vaca|bovin|novilla|vaquillona|ganado|\bcows?\b|heifer|cattle|gado|novilha|lecher|holstein|nelore|angus|brahman", re.I)
ECO = re.compile(r"ecogra|ultras|ultrason|ultrasound|\bscan|sonogra|doppler|\beco\b|ecógrafo|ecografo", re.I)
VACIA = re.compile(r"vac[ií]as?|no gestante|no pre[ñn]ada|vazias?|n[ãa]o prenhe|n[ãa]o gestante|\bopen\b|not pregnant|non[- ]?pregnant|\bempty\b|útero normal|utero normal", re.I)
PRENADA = re.compile(r"pre[ñn]|gestaci|gesta[çc][ãa]o|prenhe|pregnan|\bd[ií]as\b|\bdays?\b|feto|fetus|embri|embryo|sexaje|sexagem|gemel|twins|placentom|\bprenhez", re.I)
# Tacto o cursos: casi no muestran la imagen del ecógrafo.
SIN_ECO = re.compile(r"palpa|without ultrasound|sin ec[oó]grafo|sem ultrass|\bcurso\b|\bcourse\b|webinar|podcast", re.I)


def pista_prenez(titulo: str) -> str | None:
    if SIN_ECO.search(titulo) or not (VACA.search(titulo) and ECO.search(titulo)):
        return None
    vacia = VACIA.search(titulo)
    prenada = PRENADA.search(VACIA.sub(" ", titulo))
    if vacia and prenada:
        return "mixto"
    return "vacia" if vacia else ("prenada" if prenada else None)


# ---------- cojera en perros ----------

PERRO = re.compile(
    r"\bdogs?\b|\bdoggo|\bpupp(y|ies)\b|\bpups?\b|perr[oa]s?\b|perrit|cachorr|\bc[ãa]o\b|\bc[ãa]es\b|canin|\bk9\b|labrador|"
    r"golden retriever|german shepherd|pastor alem[aá]n|bulldog|husky|beagle|dachshund|salchicha|chihuahua|poodle|caniche|"
    r"rottweiler|pit ?bull|border collie|\bboxer\b|shih tzu|yorkie|frenchie|corgi|doberman|great dane|schnauzer",
    re.I,
)
RENGUEA = re.compile(
    r"limp|\blame\b|lameness|cojea|cojera|cojeando|\bcojo\b|renguea|rengue|(perr\w*|cachorr\w*) reng[oa]s?\b|mancand|manqueira|claudica|"
    r"favou?ring (a |his |her |one |the )?(back |front |hind )?(leg|paw)|holding (up )?(a |his |her |one |the )?(back |front |hind )?(leg|paw)|"
    r"not (using|putting weight on)|won'?t (use|put weight)|no apoya|levanta la pata",
    re.I,
)
# Los que muestran las dos cosas: antes y después, recuperación, examen de cojera.
AMBAS = re.compile(
    r"before (and|&) after|antes y despu[eé]s|antes e depois|recover|recuper|after (surgery|treatment|tplo|operation)|"
    r"post[- ]?op|rehab|walking again|runs again|vuelve a caminar|volvi[oó] a caminar|\bexam\b|examen|grading|evaluaci|"
    r"rescued|rescue|thriving|new home|finds a home|the dodo|limp is gone",
    re.I,
)
NORMAL = re.compile(
    r"normal (gait|walk|trot)|walking normal|walks normal|walk(ing)? normally|healthy (gait|walk)|sound (gait|trot)|"
    r"marcha normal|camina(ndo)? normal|andando normal|anda normal",
    re.I,
)
SIN_COJERA = re.compile(r"no limp|without (a )?limp|no longer limp|not limping|sin cojera|ya no cojea|sem mancar", re.I)
CAMINA = re.compile(r"walk|trot|gait|paseo|pasea|caminando|camina|trote|trotando|andando|passeando|caminhando|marcha", re.I)
# Otra cosa, o una marcha rara que no es cojera: mejor no sugerirlos.
DESCARTAR = re.compile(
    r"\bcats?\b|\bgat[oa]s?\b|gatit|kitten|robot|cartoon|dibujo|animat|anima[cç][aã]o|animaci[oó]n|minecraft|roblox|"
    r"amput|tripod|three[- ]legged|3[- ]legged|tres patas|\btoy\b|peluche|horse|caballo|cavalo|\bcows?\b|\bvacas?\b|sheep|goat|"
    r"compilation|compilado|compila[cç]|top ?10|asmr|podcast|live ?stream|en vivo|ao vivo|webinar|prank|broma|meme|"
    r"seizure|convuls|paraly|par[aá]lisis|wobbl|ataxia|tambale|arrastra|dragging|x-?ray|radiograf|surgery video|cirug[ií]a en vivo|"
    r"skate|surf|sling|wheelchair|silla de ruedas|carrito|cadeira de rodas|sin manos|sin patas|dos patas|two[- ]legs|two[- ]legged|"
    r"bipedal|ciego|blind|volver a caminar|walk again|cinema 4d|\b3d\b|render|blender|trick|truco|m[uú]sica|music|song|canci[oó]n|playlist|"
    r"museo|desconf|kamba|carabiner|amores perros|\bvs\b|ladrido|bark|engra[çc]ad|bizkit|guitar|riff|"
    r"lame dog walk|stunts|inch ?worm|statement|brace|ortocanis|f[oó]rmula|joint care|\bstory\b",
    re.I,
)
# Videos que explican (un veterinario hablando a cámara): casi no muestran al perro caminando.
EXPLICA = re.compile(
    r"\bwhy\b|what to do|how to|causes|reasons|explain|tips|\bsigns\b|symptom|treatment|remed|should you|when to|"
    r"porque|por qu[eé]|qu[eé] hacer|causas|s[ií]ntomas|tratamiento|consejos|c[oó]mo|remedio|dicas|o que fazer|por que|sinais|"
    r"tratamento|episode|podcast|explica|worry|when should|\bplan\b|course|curso|lecture|muscle|m[uú]sculo|anatom|daily rounds|"
    r"what to look|may be in pain|your dog may|animal health \d|online|supplement|suplement|quiropr|chiropract|paredes|walls|"
    r"\?|¿|\bwhat\b|\bhow\b|\bshould\b|ask the expert|cuidado|necesita ayuda",
    re.I,
)


def pista_perros(titulo: str, busqueda: str) -> str | None:
    if DESCARTAR.search(titulo) or EXPLICA.search(titulo) or not PERRO.search(titulo):
        return None
    if SIN_COJERA.search(titulo):
        return "normal"
    if RENGUEA.search(titulo):
        return "mixto" if AMBAS.search(titulo) or NORMAL.search(titulo) else "renguea"
    if NORMAL.search(titulo):
        return "normal"
    # «caminando con mi perro»: si salió de una búsqueda de marcha normal, se sugiere como normal
    if busqueda in BUSQUEDAS_NORMAL and CAMINA.search(titulo):
        return "normal"
    return None


BUSQUEDAS_RENGUEA = [
    "dog limping", "dog limping front leg", "dog limping back leg", "my dog is limping", "dog limping on walk",
    "dog lameness", "dog favoring leg", "limping dog vet", "perro cojea", "perro cojeando", "perro rengo",
    "cojera en perros", "perro cojea pata trasera", "cachorro mancando",
    "limping dog walking", "lame dog walking", "lame dog trot", "dog hind leg lameness walking", "dog front leg lameness",
    "dog limping shorts", "puppy limping", "perrito cojeando", "perro cojeando al caminar", "cachorro mancando da pata",
    "cão mancando pata traseira",
]
BUSQUEDAS_NORMAL = [
    "dog walking normally", "normal dog gait", "healthy dog gait", "dog trotting slow motion", "dog walking slow motion",
    "dog walking on leash", "perro caminando", "perro caminando normal", "marcha normal perro", "cachorro caminhando",
]
BUSQUEDAS_AMBAS = [
    "dog limping before and after", "dog walking after surgery recovery", "dog lameness exam", "dog gait exam vet",
    "perro cojera antes y después",
]


RECETAS = {
    "prenez": {
        "proyecto": db.PROYECTO_INICIAL,
        "archivo": "candidatos.json",
        "busquedas": [
            "ecografía vaca vacía", "ecografía bovina vaca vacía", "útero no gestante ecografía bovina", "vaca no preñada ecografía",
            "ecografía bovina preñez", "diagnóstico de gestación ecografía bovina", "ecografía vaca preñada días",
            "vaca vazia ultrassom", "ultrassonografia bovina vazia", "útero vazio vaca ultrassom", "diagnóstico de gestação bovina ultrassom",
            "open cow ultrasound", "non pregnant cow ultrasound", "bovine ultrasound open cow", "cow ultrasound not pregnant",
            "bovine pregnancy ultrasound", "cow pregnancy ultrasound days", "heifer ultrasound open",
        ],
        "pista": lambda titulo, busqueda: pista_prenez(titulo),
        "duracion": (0, 20 * 60),      # los cursos de una hora no sirven para cortar clips
    },
    "perros": {
        "proyecto": {
            "nombre": "Cojera en perros",
            "pregunta": "¿El perro renguea?",
            "contexto": (
                "Perros filmados mientras caminan, trotan o están parados, casi siempre con el celular: en la casa, "
                "en la calle o en la veterinaria. El experto decide si el perro renguea de alguna pata o camina normal."
            ),
            "opciones": [{"id": "renguea", "nombre": "Renguea"}, {"id": "normal", "nombre": "Camina normal"}],
            "ejemplo": "Ej.: no apoya la pata trasera derecha: la lleva levantada en casi todos los pasos y cabecea al pisar con la delantera.",
            "gris": 0,
        },
        "archivo": "candidatos-perros.json",
        "busquedas": BUSQUEDAS_RENGUEA + BUSQUEDAS_NORMAL + BUSQUEDAS_AMBAS,
        "pista": pista_perros,
        "duracion": (5, 180),          # videos cortos: casi todo el video es el perro caminando
    },
}


def buscar(consulta: str) -> list[dict]:
    salida = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--no-warnings", "--dump-json", f"ytsearch60:{consulta}"],
        capture_output=True, text=True,
    ).stdout
    filas = []
    for linea in salida.splitlines():
        d = json.loads(linea)
        filas.append({"id": d["id"], "title": d.get("title"), "channel": d.get("channel") or d.get("uploader"),
                      "duration": d.get("duration"), "busqueda": consulta})
    return filas


def guardar_proyecto(receta: dict, activar: bool) -> int:
    db.inicializar()
    p = receta["proyecto"]
    existente = db.fila("SELECT id FROM proyecto WHERE nombre = ?", (p["nombre"],))
    if existente:
        db.ejecutar("UPDATE proyecto SET candidatos = ? WHERE id = ?", (receta["archivo"], existente["id"]))
        proyecto_id = existente["id"]
    else:
        proyecto_id = db.crear_proyecto(**{**p, "candidatos": receta["archivo"]})
    if activar:
        db.activar(proyecto_id)
    return proyecto_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receta", choices=sorted(RECETAS), default="prenez")
    parser.add_argument("--desde", type=Path, help="jsonl de una búsqueda anterior (id, title, channel, duration, busqueda)")
    parser.add_argument("--activar", action="store_true", help="dejar el proyecto en uso en la interfaz")
    args = parser.parse_args()
    receta = RECETAS[args.receta]

    if args.desde:
        filas = [json.loads(l) for l in args.desde.read_text().splitlines()]
    else:
        with ThreadPoolExecutor(4) as grupo:
            filas = [f for lote in grupo.map(buscar, receta["busquedas"]) for f in lote]
        guardada = config.DATOS / f"busqueda-{args.receta}.jsonl"
        guardada.write_text("\n".join(json.dumps(f, ensure_ascii=False) for f in filas))

    minimo, maximo = receta["duracion"]
    vistos, candidatos = set(), []
    for f in filas:
        if f["id"] in vistos or not f.get("title") or not (minimo <= (f.get("duration") or 0) <= maximo):
            continue
        if (f.get("channel") or "").endswith(" - Topic"):      # canales de música que arma YouTube solo
            continue
        vistos.add(f["id"])
        p = receta["pista"](f["title"], f.get("busqueda", ""))
        if p:
            candidatos.append({
                "url": f"https://www.youtube.com/watch?v={f['id']}",
                "origen_id": f"Youtube-{f['id']}",
                "titulo": f["title"],
                "canal": f.get("channel") or "",
                "duracion": f.get("duration") or 0,
                "pista": p,
            })
    candidatos.sort(key=lambda c: (c["pista"], c["canal"].lower(), c["titulo"].lower()))
    destino = config.DATOS / receta["archivo"]
    destino.write_text(json.dumps(candidatos, ensure_ascii=False, indent=1))
    proyecto_id = guardar_proyecto(receta, args.activar)
    claves = [o["id"] for o in receta["proyecto"]["opciones"]] + ["mixto"]
    cuenta = {k: sum(c["pista"] == k for c in candidatos) for k in claves}
    print(f"{len(candidatos)} candidatos -> {destino}  {cuenta}  (proyecto {proyecto_id})", file=sys.stderr)


if __name__ == "__main__":
    main()
