# GUIA DEMO BASIC — Tracker de gastos con 3 agentes en n8n

Demo minimalista: **tres agentes colaborando** sobre un Chat Trigger en n8n. Todo a punta de prompting y la **Memory** del propio AI Agent. Sin Structured Output Parser, sin schemas, sin tools externas.

---

## 1. Topología

```
[Chat Trigger]
   │
   ├──► [Agente Categorizador] ──┐
   │                              │
   └──► [Agente Acumulador]   ────┤── [Merge] ──► [Agente Reportero] ──► [Chat]
              (Memory)             │
```

- **Categorizador** y **Acumulador** corren **en paralelo** desde el Chat Trigger.
- **Merge (Combine by Position, 2 inputs)** une las dos ramas para que el Reportero las pueda leer en el mismo run.
- **Reportero** redacta el mensaje final que ve el usuario.
- El Chat Trigger usa **Response Mode: Response Nodes** y el último nodo `Chat` es el que devuelve la respuesta.

> El Categorizador y el Acumulador hacen tareas distintas pero AMBOS clasifican internamente: el Categorizador clasifica el gasto del turno actual; el Acumulador re-clasifica los gastos en su Memory para llevar subtotales por categoría. Esa duplicación es a propósito para que puedan correr en paralelo sin depender uno del otro.

---

## 2. Prerrequisitos

- n8n v1.x con los nodos `@n8n/n8n-nodes-langchain.*`.
- Dos credenciales:
  - **Groq** (https://console.groq.com) → para Categorizador y Acumulador.
  - **OpenRouter** (https://openrouter.ai) → para el Reportero.
- ¿Por qué dos proveedores? El Reportero recibe los dos prompts completos a través del Merge (categorizador + acumulador + sus propios ejemplos), y eso supera el límite de **tokens por minuto** del free tier de Groq. El modelo gratis de OpenRouter (`openai/gpt-oss-120b:free`) aguanta esa carga sin caerse.

---

## 3. Estructura de carpeta

```
demo-basic/
├── prompts/
│   ├── 01-categorizador.txt
│   ├── 02-acumulador.txt
│   └── 03-reportero.txt
├── workflow/
│   └── workflow-basic.json
└── GUIA-DEMO-BASIC.md
```

Los 3 TXT son la **fuente de verdad** de los prompts. El JSON es importable directo en n8n (`Workflows → Import from File`).

---

## 4. Modelos por agente

| Agente              | Proveedor   | Modelo                          |
|---------------------|-------------|---------------------------------|
| Agente Categorizador| Groq        | `qwen/qwen3-32b`                |
| Agente Acumulador   | Groq        | `openai/gpt-oss-120b`           |
| Agente Reportero    | OpenRouter  | `openai/gpt-oss-120b:free`      |

---

## 5. Construcción nodo por nodo

### Nodo 1 — When chat message received (Chat Trigger)

- Tipo: `@n8n/n8n-nodes-langchain.chatTrigger`
- **Mode:** `Hosted Chat`, **Public available: ON**
- **Settings → Options → Response Mode:** `Response Nodes`
- Copia la **Chat URL** pública.

### Nodo 2 — Agente Categorizador (AI Agent)

- Tipo: `@n8n/n8n-nodes-langchain.agent`
- **promptType:** `define`
- **Text:** pega literal [prompts/01-categorizador.txt](prompts/01-categorizador.txt). Termina con `{{ $json.chatInput }}`.
- **hasOutputParser:** `false`.
- Sub-nodos:
  - **Chat Model:** Groq → `qwen/qwen3-32b`.
  - **Memory:** ninguna.
- Conecta `When chat message received` → `Agente Categorizador`.

### Nodo 3 — Agente Acumulador (AI Agent)

- Tipo: `@n8n/n8n-nodes-langchain.agent`
- **promptType:** `define`
- **Text:** pega literal [prompts/02-acumulador.txt](prompts/02-acumulador.txt).
- **hasOutputParser:** `false`.
- Sub-nodos:
  - **Chat Model:** Groq → `openai/gpt-oss-120b`.
  - **Memory:** **Window Buffer Memory** (`Simple Memory`), `contextWindowLength = 10`. Esto le da la "memoria del día"; al reiniciar el workflow se borra.
- Conecta `When chat message received` → `Agente Acumulador` (el MISMO output del Chat Trigger sale a ambos agentes en paralelo).

### Nodo 4 — Merge

- Tipo: `n8n-nodes-base.merge` v3.2 (ajustes por defecto: `Append`/`Combine by Position` v3.2 ya entrega los dos items al Reportero correctamente).
- **Number of Inputs:** `2`
- Conecta:
  - Input 1: `Agente Categorizador`
  - Input 2: `Agente Acumulador`

### Nodo 5 — Agente Reportero (AI Agent)

- Tipo: `@n8n/n8n-nodes-langchain.agent`
- **promptType:** `define`
- **Text:** pega literal [prompts/03-reportero.txt](prompts/03-reportero.txt). Termina con:

  ```
  REPORTE DEL CATEGORIZADOR:
  {{ $('Agente Categorizador').first().json.output }}

  REPORTE DEL ACUMULADOR:
  {{ $('Agente Acumulador').first().json.output }}
  ```

  > **Importante:** usar `.first()` (no `.item`). Después de un Merge, `.item` rompe el paired-item tracking de n8n y la expresión se pone en rojo. `.first()` toma el primer output del nodo nombrado y siempre funciona.

- **hasOutputParser:** `false`.
- Sub-nodos:
  - **Chat Model:** OpenRouter → `openai/gpt-oss-120b:free`.
  - **Memory:** ninguna.
- Conecta `Merge` → `Agente Reportero`.

### Nodo 6 — Chat (respuesta al usuario)

- Tipo: `@n8n/n8n-nodes-langchain.chat`
- **Message:** `={{ $json.output }}`
- Conecta `Agente Reportero` → `Chat`.

---

## 6. Cheatsheet de expresiones

```
# Mensaje del usuario (dentro de Categorizador y Acumulador)
{{ $json.chatInput }}

# Salidas de los agentes (texto plano) - usar SIEMPRE .first() después de Merge
{{ $('Agente Categorizador').first().json.output }}
{{ $('Agente Acumulador').first().json.output }}

# Mensaje final que se manda al chat (dentro del nodo Chat)
={{ $json.output }}
```

> Como NO usamos Structured Output Parser, `output` es **string plano**. No hay `output.reply` ni `output.data`. Los prompts están escritos para producir texto en un formato visual (`Categoria:`, `Monto:`, `Por categoria:`, etc.) que el Reportero lee tal cual.

---

## 7. Flujo de un turno (paso a paso)

1. Usuario (turno 3 del día): *"Cine con mi novia, 30k"*.
2. Chat Trigger dispara y manda el mensaje a **Agente Categorizador** y **Agente Acumulador** en paralelo.
3. **Agente Categorizador** responde:
   ```
   Categoria: Entretenimiento
   Monto: 30000
   Detalle: Cine con mi novia
   ```
4. **Agente Acumulador** ve en su Memory los gastos previos (`Rappi 45000`, `Uber 12500`), los re-categoriza junto al actual y responde:
   ```
   Gastos del dia: 3
   Total acumulado: 87500
   Ultimo gasto: 30000 (Entretenimiento)
   Por categoria:
   - Comida: 45000
   - Transporte: 12500
   - Entretenimiento: 30000
   - Servicios: 0
   - Salud: 0
   - Educacion: 0
   - Otros: 0
   Categoria dominante: Comida (51% del total)
   ```
5. **Merge** junta ambos textos.
6. **Agente Reportero** los lee con `.first()` y arma confirmación + estado del día + consejo concreto:
   > *"Listo, registre 30.000 COP en Entretenimiento (cine). Hoy llevas 87.500 COP en 3 gastos, con Comida liderando (51%). Si quieres bajar la cuota del día, mañana arma almuerzo en casa y te ahorras fácil 20-30 mil 🍳"*
7. El nodo **Chat** envía esa frase al usuario.

---

## 8. Activar y probar

1. **Importar** [workflow/workflow-basic.json](workflow/workflow-basic.json) (`Workflows → Import from File`) o construir manual con los pasos de §5.
2. Reemplazar las credenciales (Groq + OpenRouter) por las tuyas.
3. **Save** (`Ctrl+S`) y activar el switch **Active**.
4. Abrir la **Chat URL** del Chat Trigger.
5. Probar la siguiente secuencia (un mensaje por turno):
   1. `Gaste 45 lucas en Rappi`
   2. `Uber al trabajo, 12.500`
   3. `Pague la luz, 180k`
   4. `Cine con mi novia, 30k`
   5. `Compre un libro de Python por 75000`
6. Verifica que el total se vaya acumulando turno a turno y que el Reportero dé un consejo distinto según la categoría dominante.

---

## 9. Categorías cerradas

| Categoría        | Ejemplos                                        |
|------------------|-------------------------------------------------|
| Comida           | Rappi, restaurante, mercado, café               |
| Transporte       | Uber, DiDi, bus, gasolina, parqueadero          |
| Entretenimiento  | Cine, Netflix, concierto, salida con amigos     |
| Servicios        | Luz, agua, internet, gas, celular               |
| Salud            | Farmacia, EPS, gimnasio, terapia                |
| Educacion        | Curso, libro, plataforma, suscripción académica |
| Otros            | Cualquier cosa que no encaje arriba             |

---

## 10. Troubleshooting rápido

| Problema | Causa | Fix |
|----------|-------|-----|
| Expresión del Reportero en rojo (`.item`) | Merge rompe paired-item tracking | Cambiar `.item` por `.first()` |
| Reportero responde con uno solo de los dos contextos | Estás usando `$json.output` directo | Usar `$('Agente Categorizador').first().json.output` y `$('Agente Acumulador').first().json.output` |
| Groq tira error de tokens por minuto | El Reportero pide demasiado contexto al modelo gratis de Groq | Mover el Reportero a OpenRouter `openai/gpt-oss-120b:free` (es lo que ya hace este workflow) |
| El Acumulador "olvida" gastos viejos | `contextWindowLength` muy bajo | Subir el valor de `Simple Memory` (10 → 30, etc.) |
| El total se reinicia cada vez | Reiniciaste el workflow o cerraste la sesión del chat | La Memory es en RAM; eso es esperado en este demo |
