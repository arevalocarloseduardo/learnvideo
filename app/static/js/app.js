// learnvideo: comportamiento de cada pantalla. Sin dependencias.

const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];

async function pedir(url, { metodo = "POST", datos, formulario } = {}) {
  const opciones = { method: metodo, headers: {} };
  if (formulario) opciones.body = formulario;
  else if (datos !== undefined) {
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(datos);
  }
  let respuesta;
  try {
    respuesta = await fetch(url, opciones);
  } catch {
    throw new Error("No hay conexión con el servidor. ¿Sigue corriendo?");
  }
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok || cuerpo.ok === false) throw new Error(cuerpo.error || cuerpo.detalle || `Error ${respuesta.status}`);
  return cuerpo;
}

function avisar(zona, texto, tipo = "") {
  const destino = zona && ($("[data-mensaje]", zona) || zona.closest("form, section, div")?.querySelector("[data-mensaje]"));
  if (!destino) return;
  destino.textContent = texto;
  destino.dataset.tipo = tipo;
}

async function conBoton(boton, tarea) {
  if (!boton || boton.getAttribute("aria-busy") === "true") return;
  boton.setAttribute("aria-busy", "true");
  boton.disabled = true;
  try {
    await tarea();
  } finally {
    boton.removeAttribute("aria-busy");
    boton.disabled = false;
  }
}

const escribiendo = (e) => ["TEXTAREA", "INPUT", "SELECT"].includes(e.target.tagName) && e.target.type !== "radio" && e.target.type !== "checkbox";
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- global: tema, estado de la IA, pestañas del visor ----------

function iniciarGlobal() {
  const botonTema = $("[data-tema]");
  const pintarTema = () => { if (botonTema) botonTema.textContent = document.documentElement.dataset.theme === "light" ? "Tema oscuro" : "Tema claro"; };
  pintarTema();
  botonTema?.addEventListener("click", () => {
    const claro = document.documentElement.dataset.theme !== "light";
    if (claro) document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("tema", claro ? "light" : "dark"); } catch {}
    pintarTema();
  });

  const probar = $("[data-probar-ia]");
  probar?.addEventListener("click", () => conBoton(probar, async () => {
    const zona = $("#estado-ia");
    $("[data-detalle]", zona).textContent = "Probando…";
    try {
      const estado = await pedir("/api/ia/estado?probar=1", { metodo: "GET" });
      $(".indicador", zona).dataset.ok = String(estado.ok);
      $("[data-motor]", zona).textContent = estado.motor;
      $("[data-detalle]", zona).textContent = estado.ok ? "Conectado" : estado.detalle;
    } catch (error) {
      $(".indicador", zona).dataset.ok = "false";
      $("[data-detalle]", zona).textContent = error.message;
    }
  }));

  $$("[data-visor]").forEach((visor) => {
    $$("[data-pestana]", visor).forEach((pestana) => pestana.addEventListener("click", () => {
      $$("[data-pestana]", visor).forEach((p) => p.setAttribute("aria-selected", String(p === pestana)));
      $$("[data-panel]", visor).forEach((panel) => { panel.hidden = panel.dataset.panel !== pestana.dataset.pestana; });
    }));
  });

  $$("[data-recargar]").forEach((el) => setTimeout(() => location.reload(), Number(el.dataset.recargar) || 5000));
}

// ---------- enseñar ----------

function iniciarEnsenar() {
  const form = $("#form-etiqueta");
  if (!form) return;
  const guardar = () => {
    const respuesta = new FormData(form).get("respuesta");
    if (!respuesta) { avisar(form, "Elegí una respuesta: 1, 2 o 3.", "error"); return; }
    conBoton($('button[type="submit"]', form), async () => {
      try {
        await pedir("/api/etiquetas", { datos: { clip_id: form.dataset.clip, respuesta, explicacion: $("#explicacion").value } });
        location.href = "/ensenar";
      } catch (error) { avisar(form, error.message, "error"); }
    });
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); guardar(); });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); guardar(); return; }
    if (escribiendo(e) || e.metaKey || e.ctrlKey || e.altKey) return;
    const radios = $$('input[name="respuesta"]', form);
    const indice = Number(e.key) - 1;
    if (indice >= 0 && indice < radios.length) { radios[indice].checked = true; radios[indice].focus(); }
  });
  $("[data-descartar]")?.addEventListener("click", (e) => conBoton(e.currentTarget, async () => {
    try {
      await pedir(`/api/clips/${e.currentTarget.dataset.descartar}/descartar`);
      location.href = "/ensenar";
    } catch (error) { avisar(form, error.message, "error"); }
  }));
}

// ---------- validar ----------

function iniciarValidar() {
  $("[data-predecir]")?.addEventListener("click", (e) => conBoton(e.currentTarget, async () => {
    try { await pedir("/api/tandas"); location.reload(); } catch (error) { avisar(e.currentTarget.parentElement, error.message, "error"); }
  }));
  $$("[data-reintentar-tanda]").forEach((b) => b.addEventListener("click", () => conBoton(b, async () => {
    try { await pedir(`/api/tandas/${b.dataset.reintentarTanda}/reintentar`); location.reload(); } catch (error) { avisar(b.parentElement, error.message, "error"); }
  })));

  if ($("[data-esperando-tanda]")) {
    const listasAhora = () => pedir("/api/tandas/actual", { metodo: "GET" }).then((r) => r.tanda);
    (async () => {
      const inicial = await listasAhora().catch(() => null);
      for (;;) {
        await esperar(4000);
        const t = await listasAhora().catch(() => null);
        if (!t || t.estado !== "prediciendo" || (t.listas || 0) > 0 || (inicial && t.listas !== inicial.listas)) { location.reload(); return; }
      }
    })();
  }

  const veredicto = $(".veredicto");
  if (!veredicto) return;
  const clip = veredicto.dataset.clip;
  const correccion = $("#form-correccion");
  const acerto = $("[data-acerto]");
  const abrirCorreccion = () => {
    correccion.hidden = false;
    ($('input[name="respuesta_correcta"]:checked', correccion) ? $("#por-que") : $('input[name="respuesta_correcta"]', correccion))?.focus();
  };
  acerto.addEventListener("click", () => conBoton(acerto, async () => {
    try { await pedir("/api/revisiones", { datos: { clip_id: clip, acerto: true } }); location.reload(); }
    catch (error) { avisar(acerto.parentElement, error.message, "error"); }
  }));
  $("[data-se-equivoco]").addEventListener("click", abrirCorreccion);
  $("[data-cancelar]", correccion).addEventListener("click", () => { correccion.hidden = true; });
  const guardarCorreccion = () => {
    const datos = new FormData(correccion);
    if (!datos.get("respuesta_correcta")) { avisar(acerto.parentElement, "Elegí cuál era la respuesta.", "error"); return; }
    conBoton($('button[type="submit"]', correccion), async () => {
      try {
        await pedir("/api/revisiones", { datos: { clip_id: clip, acerto: false, respuesta_correcta: datos.get("respuesta_correcta"), por_que: datos.get("por_que") } });
        location.reload();
      } catch (error) { avisar(acerto.parentElement, error.message, "error"); }
    });
  };
  correccion.addEventListener("submit", (e) => { e.preventDefault(); guardarCorreccion(); });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && !correccion.hidden) { e.preventDefault(); guardarCorreccion(); return; }
    if (escribiendo(e) || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key.toLowerCase() === "a" && correccion.hidden) acerto.click();
    if (e.key.toLowerCase() === "e") { e.preventDefault(); abrirCorreccion(); }
  });
}

// ---------- cargar ----------

function iniciarCargar() {
  const cola = $("#cola");
  const refrescarCola = async () => {
    const r = await fetch("/cargar/cola").catch(() => null);
    if (r?.ok) cola.innerHTML = await r.text();
  };
  const hayTrabajo = () => $$("tr[data-estado]", cola).some((f) => ["en_cola", "bajando", "procesando"].includes(f.dataset.estado));
  (async () => { for (;;) { await esperar(3000); if (hayTrabajo()) await refrescarCola(); } })();
  cola.addEventListener("click", (e) => {
    const b = e.target.closest("[data-reintentar-video]");
    if (b) conBoton(b, async () => { await pedir(`/api/videos/${b.dataset.reintentarVideo}/reintentar`).catch(() => {}); await refrescarCola(); });
  });

  const formEnlaces = $("#form-enlaces");
  formEnlaces?.addEventListener("submit", (e) => {
    e.preventDefault();
    conBoton($('button[type="submit"]', formEnlaces), async () => {
      try {
        const r = await pedir("/api/videos", { datos: { enlaces: $("#enlaces").value } });
        avisar(formEnlaces, `Agregados: ${r.agregados}${r.repetidos ? ` · ya estaban: ${r.repetidos}` : ""}. Se procesan de a uno.`, "ok");
        $("#enlaces").value = "";
        await refrescarCola();
      } catch (error) { avisar(formEnlaces, error.message, "error"); }
    });
  });

  const formArchivos = $("#form-archivos");
  if (formArchivos) {
    const entrada = $("#archivos");
    const zona = $("[data-zona]");
    const mostrar = () => { $("[data-elegidos]").textContent = entrada.files.length ? [...entrada.files].map((f) => f.name).join(", ") : "MP4, MOV o WEBM"; };
    entrada.addEventListener("change", mostrar);
    ["dragenter", "dragover"].forEach((t) => zona.addEventListener(t, (e) => { e.preventDefault(); zona.dataset.arrastrando = "true"; }));
    ["dragleave", "drop"].forEach((t) => zona.addEventListener(t, () => { zona.dataset.arrastrando = "false"; }));
    zona.addEventListener("drop", (e) => { e.preventDefault(); entrada.files = e.dataTransfer.files; mostrar(); });
    formArchivos.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!entrada.files.length) { avisar(formArchivos, "Elegí al menos un archivo.", "error"); return; }
      const datos = new FormData();
      [...entrada.files].forEach((f) => datos.append("archivos", f));
      conBoton($('button[type="submit"]', formArchivos), async () => {
        try {
          const r = await pedir("/api/subir", { formulario: datos });
          avisar(formArchivos, `Subidos: ${r.agregados}${r.repetidos ? ` · repetidos: ${r.repetidos}` : ""}.`, "ok");
          entrada.value = ""; mostrar();
          await refrescarCola();
        } catch (error) { avisar(formArchivos, error.message, "error"); }
      });
    });
  }

  const formCandidatos = $("#form-candidatos");
  if (formCandidatos) {
    const boton = $("[data-importar]", formCandidatos);
    const contar = () => {
      const n = $$('input[name="ids"]:checked', formCandidatos).length;
      boton.disabled = n === 0;
      $(".boton-texto", boton).textContent = n ? `Importar ${n} ${n === 1 ? "video" : "videos"}` : "Importar seleccionados";
    };
    formCandidatos.addEventListener("change", (e) => {
      if (e.target.dataset.todos) $$(`input[data-grupo="${e.target.dataset.todos}"]`, formCandidatos).forEach((c) => { c.checked = e.target.checked; });
      contar();
    });
    formCandidatos.addEventListener("submit", (e) => {
      e.preventDefault();
      const ids = $$('input[name="ids"]:checked', formCandidatos).map((c) => c.value);
      conBoton(boton, async () => {
        try {
          const r = await pedir("/api/candidatos", { datos: { ids } });
          avisar(formCandidatos, `Importados: ${r.agregados}. Se bajan y procesan de a uno; podés empezar a enseñar apenas haya clips.`, "ok");
          $$('input[name="ids"]:checked', formCandidatos).forEach((c) => c.closest("li").remove());
          contar();
          await refrescarCola();
        } catch (error) { avisar(formCandidatos, error.message, "error"); }
      });
    });
  }
}

// ---------- criterios ----------

async function esperarManualNuevo(versionAntes, zona) {
  avisar(zona, "La IA está reescribiendo el manual…");
  for (let i = 0; i < 90; i++) {
    await esperar(4000);
    const r = await pedir("/api/ocupado", { metodo: "GET" }).catch(() => null);
    if (r && r.manual_version > versionAntes) { location.reload(); return; }
    if (r && !r.ia && i > 1) { avisar(zona, "La IA terminó sin escribir una versión nueva. Mirá el estado del motor abajo a la izquierda.", "error"); return; }
  }
}

function iniciarCriterios() {
  const raiz = $("#criterios");
  if (!raiz) return;
  const lectura = $("[data-lectura]", raiz);
  const edicion = $("[data-edicion]", raiz);
  $("[data-editar]", raiz)?.addEventListener("click", () => { lectura.hidden = true; edicion.hidden = false; $("#texto-manual").focus(); });
  $("[data-cancelar]", raiz)?.addEventListener("click", () => { lectura.hidden = false; edicion.hidden = true; });
  edicion?.addEventListener("submit", (e) => {
    e.preventDefault();
    conBoton($('button[type="submit"]', edicion), async () => {
      try { await pedir("/api/manual", { datos: { texto: $("#texto-manual").value } }); location.reload(); }
      catch (error) { avisar(raiz, error.message, "error"); }
    });
  });
  $$("[data-reescribir]", raiz).forEach((b) => b.addEventListener("click", () => conBoton(b, async () => {
    try { await pedir("/api/manual/reescribir"); await esperarManualNuevo(Number(raiz.dataset.version), b.parentElement); }
    catch (error) { avisar(b.parentElement, error.message, "error"); }
  })));
}

// ---------- proyectos ----------

function iniciarProyectos() {
  $$("[data-activar]").forEach((boton) => boton.addEventListener("click", () => conBoton(boton, async () => {
    try {
      await pedir(`/api/proyectos/${boton.dataset.activar}/activar`);
      location.href = "/";
    } catch (error) {
      avisar(boton.closest("section"), error.message, "error");
    }
  })));

  const form = $("#form-proyecto");
  form?.addEventListener("submit", (e) => {
    e.preventDefault();
    conBoton($("[type=submit]", form), async () => {
      const datos = Object.fromEntries(new FormData(form));
      datos.gris = form.elements.gris.checked;
      try {
        await pedir("/api/proyectos", { datos });
        location.href = "/cargar";
      } catch (error) {
        avisar(form, error.message, "error");
      }
    });
  });
}

// ---------- resultados: curva de aprendizaje ----------

function dibujarCurva(figura) {
  const datos = JSON.parse($("[data-curva]", figura).textContent || "{}");
  const series = [
    { clave: "ia_ensenada", nombre: "IA enseñada", color: "var(--serie-1)" },
    { clave: "clasificador", nombre: "Clasificador", color: "var(--serie-contexto)" },
  ].filter((s) => datos[s.clave]?.length);
  if (!series.length) return;
  const principal = datos.ia_ensenada || datos[series[0].clave];
  const tooltip = $(".tooltip", figura);
  const NS = "http://www.w3.org/2000/svg";
  const el = (tipo, atributos = {}, padre) => {
    const nodo = document.createElementNS(NS, tipo);
    Object.entries(atributos).forEach(([k, v]) => nodo.setAttribute(k, v));
    padre?.appendChild(nodo);
    return nodo;
  };

  const render = () => {
    $("svg", figura)?.remove();
    const ancho = Math.max(figura.clientWidth, 320);
    const alto = 300;
    const m = { arriba: 16, derecha: 110, abajo: 44, izquierda: 48 };
    const xs = principal.map((p) => p.n_ejemplos);
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    const x = (v) => m.izquierda + (xmax === xmin ? 0.5 : (v - xmin) / (xmax - xmin)) * (ancho - m.izquierda - m.derecha);
    const y = (v) => m.arriba + (1 - v) * (alto - m.arriba - m.abajo);
    const svg = el("svg", { viewBox: `0 0 ${ancho} ${alto}`, role: "img", "aria-label": "Acierto por tanda según la cantidad de ejemplos" });
    figura.prepend(svg);

    [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
      el("line", { x1: m.izquierda, x2: ancho - m.derecha, y1: y(v), y2: y(v), style: `stroke: var(--grilla); stroke-width: 1` }, svg);
      const t = el("text", { x: m.izquierda - 8, y: y(v) + 4, "text-anchor": "end", class: "eje" }, svg);
      t.textContent = `${v * 100}%`;
    });
    const azar = el("text", { x: ancho - m.derecha + 8, y: y(0.5) + 4, class: "eje" }, svg);
    azar.textContent = "azar";
    principal.forEach((p) => {
      const t = el("text", { x: x(p.n_ejemplos), y: alto - m.abajo + 20, "text-anchor": "middle", class: "eje" }, svg);
      t.textContent = p.n_ejemplos;
    });
    const tituloX = el("text", { x: m.izquierda, y: alto - 4, class: "eje" }, svg);
    tituloX.textContent = "ejemplos que tenía al predecir";

    const finales = [];
    series.forEach((s) => {
      const puntos = datos[s.clave];
      if (puntos.length > 1) {
        el("polyline", {
          points: puntos.map((p) => `${x(p.n_ejemplos)},${y(p.acierto)}`).join(" "),
          style: `fill: none; stroke: ${s.color}; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round`,
        }, svg);
      }
      puntos.forEach((p) => el("circle", { cx: x(p.n_ejemplos), cy: y(p.acierto), r: 4, style: `fill: ${s.color}; stroke: var(--fondo); stroke-width: 2` }, svg));
      const ultimo = puntos[puntos.length - 1];
      finales.push({ s, y: y(ultimo.acierto), x: x(ultimo.n_ejemplos) });
    });
    const chocan = finales.length === 2 && Math.abs(finales[0].y - finales[1].y) < 16;
    if (!chocan) finales.forEach(({ s, x: fx, y: fy }) => {
      const t = el("text", { x: fx + 10, y: fy + 4, class: "rotulo-serie" }, svg);
      t.textContent = s.nombre;
    });

    const cruz = el("line", { y1: m.arriba, y2: alto - m.abajo, style: "stroke: var(--texto-3); stroke-width: 1", visibility: "hidden" }, svg);
    const mostrar = (indice) => {
      const p = principal[indice];
      if (!p) return;
      cruz.setAttribute("x1", x(p.n_ejemplos)); cruz.setAttribute("x2", x(p.n_ejemplos)); cruz.setAttribute("visibility", "visible");
      tooltip.replaceChildren();
      const cabeza = document.createElement("span");
      cabeza.className = "muy-tenue";
      cabeza.textContent = `Tanda ${p.tanda} · ${p.n_ejemplos} ejemplos`;
      tooltip.appendChild(cabeza);
      series.forEach((s) => {
        const punto = datos[s.clave].find((q) => q.tanda === p.tanda);
        if (!punto) return;
        const fila = document.createElement("span");
        fila.className = "fila";
        const clave = document.createElement("i");
        clave.style.background = s.color;
        const valor = document.createElement("strong");
        valor.textContent = `${Math.round(punto.acierto * 100)}%`;
        const nombre = document.createElement("span");
        nombre.className = "tenue";
        nombre.textContent = `${s.nombre} · ${punto.aciertos} de ${punto.n}`;
        fila.append(clave, valor, nombre);
        tooltip.appendChild(fila);
      });
      tooltip.hidden = false;
      const izquierda = Math.min(x(p.n_ejemplos) + 12, ancho - tooltip.offsetWidth - 4);
      tooltip.style.left = `${Math.max(izquierda, 0)}px`;
      tooltip.style.top = `${m.arriba}px`;
      figura.dataset.indice = indice;
    };
    const ocultar = () => { cruz.setAttribute("visibility", "hidden"); tooltip.hidden = true; };
    const zona = el("rect", { x: m.izquierda - 12, y: 0, width: ancho - m.izquierda - m.derecha + 24, height: alto - m.abajo, fill: "transparent" }, svg);
    zona.addEventListener("pointermove", (e) => {
      const caja = svg.getBoundingClientRect();
      const px = ((e.clientX - caja.left) / caja.width) * ancho;
      let mejor = 0;
      principal.forEach((p, i) => { if (Math.abs(x(p.n_ejemplos) - px) < Math.abs(x(principal[mejor].n_ejemplos) - px)) mejor = i; });
      mostrar(mejor);
    });
    zona.addEventListener("pointerleave", ocultar);
    figura.tabIndex = 0;
    figura.onfocus = () => mostrar(Number(figura.dataset.indice || principal.length - 1));
    figura.onblur = ocultar;
    figura.onkeydown = (e) => {
      const actual = Number(figura.dataset.indice || principal.length - 1);
      if (e.key === "ArrowRight") { e.preventDefault(); mostrar(Math.min(actual + 1, principal.length - 1)); }
      if (e.key === "ArrowLeft") { e.preventDefault(); mostrar(Math.max(actual - 1, 0)); }
    };
  };
  render();
  let espera;
  window.addEventListener("resize", () => { clearTimeout(espera); espera = setTimeout(render, 120); });
}

function iniciarResultados() {
  const figura = $("#grafico-curva");
  if (figura) dibujarCurva(figura);
  $("[data-comparar]")?.addEventListener("click", (e) => conBoton(e.currentTarget, async () => {
    const zona = e.currentTarget.parentElement;
    try {
      await pedir("/api/comparar");
      avisar(zona, "Corriendo la comparación. Tarda unos minutos; la página se actualiza sola.");
      for (;;) {
        await esperar(5000);
        const r = await pedir("/api/ocupado", { metodo: "GET" }).catch(() => null);
        if (r && !r.ia) { location.reload(); return; }
      }
    } catch (error) { avisar(zona, error.message, "error"); }
  }));
}

iniciarGlobal();
({ ensenar: iniciarEnsenar, validar: iniciarValidar, cargar: iniciarCargar, criterios: iniciarCriterios, proyectos: iniciarProyectos, resultados: iniciarResultados })[document.body.dataset.pagina]?.();
