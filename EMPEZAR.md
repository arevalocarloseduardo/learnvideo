# Cómo hacerlo andar

Guía para probar learnvideo en tu compu, o para pasársela a tu agente (Claude Code, Codex,
Cursor…). Al final tenés la app en **http://localhost:8765** con el proyecto **«¿Está
preñada?»**: le enseñás a la IA con ecografías bovinas, la IA predice ecografías que no vio y
vos le decís si acertó.

¿Lo va a hacer tu agente? Saltá a [Para tu agente](#para-tu-agente).

## Qué necesitás

- **macOS o Linux.** En Windows, usá WSL (Ubuntu). Está probado en macOS con Apple Silicon.
- **Espacio en disco:** ~1 GB para instalar en macOS (en Linux ~4 GB, porque PyTorch trae las
  librerías de CUDA aunque no tengas placa de video), más ~10 MB por minuto de video que bajes.
- **Algo para la IA**, una de estas tres:
  - **Tu suscripción de Claude** (Pro, Max, Team o Enterprise) con Claude Code instalado. No
    cobra por llamada: descuenta de tu límite de uso.
  - **Una API key de Anthropic.** Cobra por uso; la app se frena sola al llegar a US$20.
  - **Nada**, si solo querés ver la interfaz: el modo prueba inventa las respuestas.

## 1. Instalar lo necesario

macOS, con [Homebrew](https://brew.sh):

```bash
brew install uv ffmpeg git
```

Linux (Debian o Ubuntu):

```bash
sudo apt install -y ffmpeg git curl
```

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Claude Code, si vas a usar tu suscripción:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Python no hace falta instalarlo: uv baja la versión que corresponde (3.12).

## 2. Bajar el código e instalar

```bash
git clone https://github.com/arevalocarloseduardo/learnvideo.git
```

```bash
cd learnvideo && uv sync
```

La primera vez tarda unos minutos porque baja PyTorch.

## 3. Conectar la IA

**Con tu suscripción de Claude (recomendado para probar).** Corré esto en una terminal:

```bash
bash scripts/guardar_token.sh
```

Se abre el navegador y aprobás con tu cuenta de Claude. Si el navegador te muestra un código,
pegalo en la terminal donde dice «Paste code here». Aparece un token largo que empieza con
`sk-ant-oat`: copialo y tocá Enter. El script lo guarda en `.env` sin mostrarlo. El token dura
un año. También sirve `claude auth login`, pero ese login a veces se revoca solo y hay que
repetirlo.

Con el token pasa lo mismo que con una contraseña: no lo pegues en un chat ni se lo muestres a
nadie. Tampoco corras el script con `!` desde el chat de un agente, porque el token quedaría en
la conversación.

**Con una API key.** Si todavía no tenés `.env`, copiá el de ejemplo:

```bash
cp .env.example .env
```

Después abrí `.env`, sacale el `#` a la línea `ANTHROPIC_API_KEY=` y completala con tu key. Si
hay API key, la app usa la API en lugar de la suscripción.

**Sin IA, solo para ver la interfaz.** En el paso 5, arrancá con `LEARNVIDEO_IA=prueba` adelante
del comando.

## 4. Traer ecografías de prueba de YouTube

```bash
uv run python scripts/candidatos.py --receta prenez --activar
```

Busca en YouTube unos 150 videos de ecografías bovinas y anota qué dice cada título: preñada,
vacía o las dos. Solo lee los títulos: no baja ningún video. Si ya tenés ecografías propias,
podés saltear este paso e ir al [paso 7](#7-con-tus-propias-ecografías-la-prueba-en-serio).

Dos cosas de estos videos:

- **Hay muchas menos vacías que preñadas** (unas 20 contra 125), y casi todas las vacías son
  del canal KeeboVet. Ese canal también tiene unas 60 preñadas, así que la IA no puede adivinar
  la respuesta por el canal.
- **Muchos videos arrancan mostrando al veterinario, la vaca o el equipo**, y recién después la
  ecografía. Esos clips se descartan a mano (paso 6).

## 5. Levantar la app

```bash
uv run uvicorn app.main:app --port 8765
```

Abrí http://localhost:8765. Arriba a la izquierda tiene que decir «¿Está preñada?». Abajo, en
«Motor de IA», tocá **Probar conexión**: tiene que quedar en «Conectado».

Dejá esa terminal abierta mientras la usás: ahí corren la descarga y el procesado de videos.
Para frenarla, Ctrl+C. Todo queda guardado en `data/`: si la volvés a levantar, sigue donde
estaba.

## 6. Probar el circuito (unos 40 minutos)

1. **Cargar.** En «Videos que encontré en YouTube», tildá «todos» en «Vacía» y en «Muestran las
   dos». En «Preñada», elegí unos 30 videos. Tocá **Importar seleccionados**. Se bajan de a uno,
   alternando vacías y preñadas, y primero los más cortos. Cada video se corta en clips de hasta
   12 segundos.
2. **Enseñar.** Los clips aparecen apenas están listos.
   - Si el clip no muestra la ecografía (se ve al veterinario, la vaca, un logo o una
     explicación), tocá **Descartar clip**.
   - Si la muestra, respondé «Preñada», «Vacía» o «No se puede saber» (atajos `1` `2` `3`).
     Escribí en una línea qué ves y dónde: la vesícula con líquido (lo negro), el embrión, el
     latido, los placentomas; o, en una vacía, el útero sin líquido.
   - Decí «Vacía» solo si el clip recorre bien el útero. Si no se llega a ver, poné «No se puede
     saber».
   - Guardá con `⌘↵` (o Ctrl+Enter). El título del video aparece como pista, pero la IA nunca lo
     ve.
3. **Validar.** Con 5 clips enseñados de cada respuesta ya puede predecir. Tocá **Predecir una
   tanda**: la IA mira 10 clips que no vio, en unos 2 minutos. Por cada uno decile si acertó
   (`A`) o si se equivocó (`E`). Si se equivocó, marcá la respuesta correcta y qué tendría que
   haber visto. Cada validación también le enseña.
4. **Resultados.** Después de 3 o 4 tandas, fijate si el acierto sube de una tanda a otra. Al
   final tocá **Comparar**: la app vuelve a predecir los clips validados con la IA sola, sin tus
   ejemplos. Si la IA con tus ejemplos acierta más, está aprendiendo de lo que le enseñás. Mirá
   también la tabla «¿Aprende lo que le enseñás o reconoce el canal?»: si acierta mucho más en
   canales que ya vio que en canales nuevos, está reconociendo el canal y no la preñez.

**Criterios** muestra el manual que la IA arma con tus explicaciones. Lo podés editar.

## 7. Con tus propias ecografías (la prueba en serio)

Los videos de YouTube sirven para ver que el circuito anda. La prueba que vale es con
ecografías de un mismo veterinario:

- **Un día de trabajo:** preñadas y vacías hechas con el mismo equipo. Si se puede, un video por
  vaca, de 10 a 30 segundos, recorriendo bien el útero.
- **Mejor exportarlos del ecógrafo** (por USB, en MP4 o MOV). Si no se puede, filmá la pantalla
  con el celular apoyado y quieto, encuadrando solo la imagen y sin reflejos.
- **Anotá el diagnóstico confirmado de cada vaca**, por ejemplo en el nombre del archivo, para
  validar contra la verdad y no contra lo que parecía.
- **Creá un proyecto aparte** para no mezclarlos con los de YouTube. Tocá el proyecto de arriba
  del menú, andá a «Nuevo proyecto», poné la pregunta y las dos respuestas, y marcá «Imágenes en
  blanco y negro».
- **Subilos en Cargar**, en «O subí archivos de video». El texto fijo de la pantalla del equipo
  (datos de la vaca, profundidad, logo) se tapa antes de que la IA lo vea. Con la pestaña «Lo que
  ve la IA» lo podés revisar.

## Cuánto gasta

- Bajar, cortar y procesar videos corre en tu compu y no usa la IA. Enseñar tampoco.
- Cada tanda son unas 11 llamadas, con unos 150 mil tokens de entrada en total. Con la
  suscripción descuenta de tu límite de Claude. Con API key cuesta cerca de US$1 por tanda
  con `claude-opus-5`.
- «Comparar», en Resultados, hace 2 llamadas más por cada clip validado. Es lo más caro:
  usalo al final.
- Para gastar menos, poné `LEARNVIDEO_MODELO=claude-sonnet-5` en `.env`.

## Si algo falla

| Qué pasa | Qué hacer |
|---|---|
| «El login de Claude Code venció o lo revocaron» | Corré `bash scripts/guardar_token.sh` de nuevo. No hace falta reiniciar. |
| «No encontré el comando `claude`» | Instalá Claude Code (paso 1) o usá una API key. |
| Un video queda en «error» | Tocá **Reintentar** en Cargar. YouTube a veces bloquea alguno: si sigue fallando, salteálo. |
| Muchos clips no son ecografías | Descartalos: es normal en los videos de YouTube. Con videos propios no pasa. |
| «Address already in use» | Ya hay algo en el puerto 8765: usá `--port 8766` y abrí esa dirección. |
| El disco se llena | Borrá los originales de `data/videos/` que empiezan con `Youtube-`: los clips ya están cortados y, si hiciera falta, se vuelven a bajar. |
| `ffmpeg` o `ffprobe` no encontrados | Instalalo (paso 1) y volvé a levantar la app. |

## Otro tema de prueba: perros que renguean

Hay un segundo proyecto de prueba, «¿El perro renguea?», con videos de YouTube más fáciles de
juzgar a simple vista:

```bash
uv run python scripts/candidatos.py --receta perros --activar
```

Para volver a las vacas, tocá el proyecto de arriba del menú y elegí «¿Está preñada?». Cada
proyecto guarda sus propios clips, ejemplos y manual: nada se mezcla.

## Para tu agente

Pegale esto a tu agente, desde la carpeta donde quieras el proyecto:

> Cloná https://github.com/arevalocarloseduardo/learnvideo y seguí su EMPEZAR.md para dejarme
> learnvideo andando en http://localhost:8765 con el proyecto de ecografías bovinas
> («¿Está preñada?»). Instalá lo que falte. El login de Claude lo hago yo: decime qué comando
> correr en mi terminal y esperame. No me muestres ni pegues ningún token. Dejá el servidor
> corriendo en una terminal que yo pueda ver. No importes ni bajes videos sin preguntarme.

Reglas para el agente:

- Instalá con `uv sync` y corré todo con `uv run`. No uses pip.
- El paso 3 lo hace la persona, en su terminal, porque necesita el navegador. Nunca leas,
  imprimas ni copies el token ni el contenido de `.env`. Para saber si la IA está conectada, abrí
  `http://localhost:8765/api/ia/estado?probar=1`: tiene que devolver `"ok": true`.
- El servidor tiene que quedar corriendo en primer plano en una terminal visible, no atado a tu
  sesión. Los hilos que bajan y procesan videos viven en ese proceso.
- `data/` (videos, clips y la base SQLite) y `.env` no se suben nunca a git: ya están en
  `.gitignore`.
- Para probar la interfaz sin gastar IA: `LEARNVIDEO_IA=prueba LEARNVIDEO_DATOS=data-prueba uv run
  uvicorn app.main:app --port 8766`.
- Si vas a tocar la interfaz, leé `DESIGN.md` primero: ahí están los tokens y las reglas.
