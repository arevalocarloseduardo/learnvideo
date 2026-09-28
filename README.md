# learnvideo

Enseñarle a una IA a leer videos con ejemplos explicados por un experto. Sirve para cualquier
pregunta de sí o no sobre un video: cada pregunta es un **proyecto** con sus propios clips,
ejemplos y manual. Vienen dos de prueba: preñez bovina por ecografía y cojera en perros.

**¿Querés probarlo?** Seguí [EMPEZAR.md](EMPEZAR.md): instalación paso a paso, cómo conectar la
IA y cómo probar el circuito completo. También sirve para pasársela a tu agente.

1. **Cargar**: pegás links (YouTube, TikTok, Instagram) o subís archivos. Cada video se corta
   en clips de hasta 12 s.
2. **Enseñar**: mirás cada clip, respondés (preñada / vacía / no se puede saber) y explicás
   qué ves. Atajos: `1` `2` `3` y `⌘↵`.
3. **Validar**: la IA predice tandas de 10 clips que no vio. Le decís si acertó (`A`) o se
   equivocó (`E`), con la respuesta correcta y por qué. Cada validación es un ejemplo más.
4. **Criterios**: el manual que la IA escribe con tus explicaciones y correcciones. Lo podés
   editar.
5. **Resultados**: el acierto por tanda, la comparación contra la IA sin enseñarle nada, y si
   está aprendiendo lo que le enseñás o reconociendo el canal.

Arriba del menú está el proyecto en uso: tocándolo se cambia de proyecto o se crea uno nuevo
(pregunta, las dos respuestas y qué muestran los videos). Los proyectos en blanco y negro
(ecografías, rayos X) ven los cuadros en gris y descartan los clips con color; los demás, en color.

## Cómo aprende

- **Clasificador propio**: cada clip se convierte en una huella numérica con DINOv2 (un
  modelo de visión ya entrenado) y se entrena una regresión logística con tus etiquetas.
- **IA con ejemplos y explicaciones**: la IA recibe 8 cuadros del clip, los 3 casos
  enseñados que más se le parecen (con tus explicaciones) y el manual de criterios.
- La IA **nunca ve el título ni el texto de la pantalla**: se recorta la zona que se mueve y
  se tapa el texto fijo, como logos o datos del equipo (la pestaña «Lo que ve la IA» lo muestra).
- El acierto es honesto: cada clip se predice antes de que lo veas, solo con lo que se sabía
  al crear la tanda y nunca con ejemplos del mismo video (sería la misma vaca).

## Correrlo

Necesita [uv](https://docs.astral.sh/uv/) y `ffmpeg`. El detalle está en [EMPEZAR.md](EMPEZAR.md).

```bash
uv sync
uv run python scripts/candidatos.py --receta perros --activar
uv run uvicorn app.main:app --port 8765
```

Abrí http://localhost:8765. Los datos quedan en `data/` (videos, clips, base SQLite).

### Motor de IA

| Modo | Cuándo se usa | Costo |
|---|---|---|
| Sesión de Claude Code | por defecto: usa `claude -p` con tu login (`claude auth login`) | entra en tu suscripción |
| API de Anthropic | si hay `ANTHROPIC_API_KEY` en `.env` | por uso, con tope `LEARNVIDEO_TOPE_USD` (20 por defecto) |
| Prueba | `LEARNVIDEO_IA=prueba`: respuestas inventadas, solo para ver la interfaz | gratis |

El modo sesión es para probar en tu máquina. Cuando lo use otra gente tiene que ir por la API.
Modelo: `LEARNVIDEO_MODELO` (por defecto `claude-opus-5`). Ver `.env.example`.

El login de `claude auth login` se puede revocar solo (pasó dos veces). Para que no se corte,
corré `bash scripts/guardar_token.sh` en una terminal: genera un token de un año con
`claude setup-token` y lo guarda en `.env` como `CLAUDE_CODE_OAUTH_TOKEN` sin mostrarlo. No lo
corras con `!` en el chat, así el token no queda en la conversación. No hace falta reiniciar.

### Videos de prueba de YouTube

`scripts/candidatos.py` busca videos en YouTube para un tema de prueba (solo lee los títulos,
no baja nada), anota la respuesta que sugiere cada título y crea el proyecto:

```bash
uv run python scripts/candidatos.py --receta perros --activar   # cojera en perros
uv run python scripts/candidatos.py --receta prenez             # ecografías bovinas
```

Quedan en `data/candidatos-perros.json` y `data/candidatos.json`, y se importan desde
«Cargar»: se bajan alternando las respuestas y primero los videos cortos, así hay clips de
las dos enseguida. Sirven para probar, no para el producto: ahí cada cliente usa sus propios
videos.

## Límites conocidos

- Con videos de YouTube hay pocas vacías y casi todas de un mismo canal: la IA puede aprender
  a reconocer el canal. La tabla «¿Aprende la preñez o el canal?» lo muestra.
- La prueba en serio es con clips de un veterinario: un día de ecografías, preñadas y vacías
  con el mismo equipo, con el diagnóstico confirmado después.
- «Vacía» solo se puede afirmar si el clip recorre todo el útero.

## Estructura

```
app/main.py          servidor y API
app/ingesta.py       bajar, cortar, recortar, tapar texto, hojas de cuadros
app/huellas.py       huellas DINOv2
app/aprendizaje.py   clasificador, casos parecidos, manual, tandas, validación
app/evaluacion.py    métricas
app/ia/              motores: sesión (claude -p), API de Anthropic, prueba
DESIGN.md            dirección de arte y tokens de la interfaz
```
