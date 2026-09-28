# DESIGN.md — learnvideo

## Sujeto
Herramienta para que un experto le enseñe a una IA a leer videos: etiqueta clips, la IA
predice clips nuevos y el experto valida o corrige. Nació con ecografías bovinas y sirve para
cualquier pregunta de sí o no (cada una es un proyecto). El único trabajo de la interfaz: que
enseñar y validar sea rápido y que se vea si la IA está aprendiendo.

## Dirección de arte: «consola de ecógrafo» (técnica-precisa)
- La imagen es la protagonista, como en la pantalla del equipo: el **visor siempre es
  oscuro**, en los dos temas, para que se lean los grises finos de la ecografía.
- Las lecturas (confianza, días, conteos, porcentajes) van en monoespaciada, como los
  datos sobreimpresos del ecógrafo (profundidad, ganancia, MHz).
- El acento es el **ámbar de calibre** (el color de las marcas de medición del equipo) y
  se usa solo en lo que se puede tocar.
- Nivel de producción: **A · UI de producto**. Cero coreografía; microinteracciones de
  menos de 200 ms; las acciones que se repiten cien veces (etiquetar) no animan.
- Momento firma: **el calibre de confianza**. La probabilidad se muestra como una medición
  del ecógrafo: una regla con marcas de la respuesta del no a la del sí (VACÍA → PREÑADA)
  y dos cruces de calibre unidas por una línea punteada. La misma regla se repite en el progreso y en los resultados.
- Riesgo declarado: tema oscuro por defecto (se justifica por la imagen); el tema claro
  existe para usarlo al sol, con el visor oscuro igual.

## Color (OKLCH, neutros teñidos hacia el ámbar, croma < 0.01)
| Token | Oscuro (default) | Claro | Rol |
|---|---|---|---|
| `--fondo` | `oklch(0.19 0.006 75)` | `oklch(0.975 0.004 75)` | fondo de la app |
| `--superficie` | `oklch(0.225 0.006 75)` | `oklch(0.993 0.002 75)` | paneles |
| `--superficie-2` | `oklch(0.265 0.007 75)` | `oklch(0.955 0.005 75)` | elevado / hover |
| `--borde` | `oklch(0.95 0.01 75 / 0.10)` | `oklch(0.25 0.01 75 / 0.12)` | filetes al 10 % |
| `--texto` | `oklch(0.93 0.008 75)` | `oklch(0.22 0.01 75)` | texto principal |
| `--texto-2` | `oklch(0.74 0.01 75)` | `oklch(0.42 0.01 75)` | secundario |
| `--texto-3` | `oklch(0.645 0.01 75)` | `oklch(0.52 0.01 75)` | etiquetas, ayudas |
| `--acento` | `oklch(0.80 0.13 78)` | `oklch(0.74 0.14 72)` | SOLO interactivos (fondo de botón primario, foco, selección) |
| `--acento-tinta` | `oklch(0.21 0.03 78)` | `oklch(0.21 0.03 78)` | texto sobre el acento |
| `--acento-link` | `oklch(0.82 0.12 78)` | `oklch(0.50 0.12 65)` | links sobre fondo |
| `--visor` | `oklch(0.14 0.004 75)` | `oklch(0.14 0.004 75)` | fondo del visor (siempre oscuro) |
| `--bien` | `oklch(0.76 0.09 150)` | `oklch(0.48 0.10 150)` | acertó (estado, no acento) |
| `--mal` | `oklch(0.72 0.12 28)` | `oklch(0.52 0.15 28)` | se equivocó (estado, no acento) |

Nunca `#000` ni `#fff`. En oscuro no hay sombras: la elevación se marca con superficies
más claras. Brillo entre contenedores vecinos: diferencia ≤ 12 %.

Contraste verificado (WCAG): todo texto ≥ 4.5:1 sobre fondo, superficie y superficie-2 en
los dos temas; texto sobre el acento 9.3:1 (oscuro) y 7.5:1 (claro).

## Gráficos
- Forma «énfasis»: la serie protagonista (IA enseñada) en azul, el resto en gris de contexto.
  Azul `#3987e5` en oscuro y `#2a78d6` en claro; gris `#898781` en los dos. Validado con el
  validador de dataviz sobre `--superficie` (CVD ΔE 15.9, visión normal ΔE ≥ 17, contraste ≥ 3:1;
  el gris falla el piso de croma a propósito: es el gris de énfasis, no una serie categórica).
- Líneas de 2 px, puntos de 8 px con anillo de 2 px del color de la superficie, grilla de
  1 px sólida y apagada, leyenda siempre (2 series) + rótulo directo al final de cada línea,
  tooltip con cruz vertical y tabla equivalente debajo de cada gráfico.

## Tipografía
- Sans: **Hanken Grotesk** 400 / 500 / 600 (texto e interfaz).
- Mono: **IBM Plex Mono** 400 / 500, con `tabular-nums` (lecturas, datos, etiquetas).
- Self-hosteadas en `app/static/fonts`, subset latin, `font-display: swap`.
- Escala 1.25 sobre 16 px: 0.8 · 1 · 1.25 · 1.563 · 1.953 · 2.441 rem. El 0.8 solo para
  etiquetas en mono mayúscula (+0.08 em). Cuerpo 16 px mínimo.
- Interlínea: cuerpo 1.55, títulos 1.15. Tracking de títulos −0.01 em.
- Medida: 65 ch en textos largos (manual de criterios, explicaciones).

## Espaciado, radios, sombras
- Escala de 8: 4 · 8 · 16 · 24 · 32 · 48 · 64 · 96 px (`--e-1` … `--e-8`).
- Radios chicos, de instrumento: 4 px en controles, 8 px en paneles. Nada de 16 px.
- Sombra solo en tema claro y solo en lo que flota: `0 1px 2px oklch(0.3 0.02 75 / .06),
  0 4px 12px oklch(0.3 0.02 75 / .06)`.
- Botones: padding horizontal = 2 × vertical; objetivos táctiles ≥ 44 px.

## Motion
- 160 ms `cubic-bezier(0.22, 1, 0.36, 1)` para hover, press y aparición de paneles.
- Botones se hunden a `scale(0.97)`. Solo `transform` y `opacity`.
- Etiquetar y validar no animan (se hacen cientos de veces). Hover solo con
  `@media (hover: hover)`. `prefers-reduced-motion` reemplaza todo por un fade de 0.2 s.

## Proyectos
- El proyecto en uso va arriba del riel, con rótulo mono «PROYECTO» y flechas de selector:
  es la puerta a la pantalla Proyectos. En mobile queda al lado de la marca, truncado.
- En la lista, el proyecto en uso se marca como una opción elegida (borde ámbar, igual que
  la respuesta tildada al enseñar) más el chip «en uso». Datos en mono debajo del título.

## Estados obligatorios
Hover, focus-visible (anillo ámbar con `box-shadow`), cargando (esqueleto del visor, no
spinner), vacío (con la acción que sigue), error (qué pasó y qué hacer), texto largo y
mobile (botones de decisión abajo, al alcance del pulgar).
