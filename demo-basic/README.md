# Requisitos previos a la práctica

Antes de empezar las demos, crea las siguientes cuentas. Todas son **gratis** y no piden tarjeta para el plan free.

---

## 1. n8n Cloud — donde corre todo el workflow

1. Entra a **https://n8n.io/cloud/** y haz click en **Get started for free**.
2. Regístrate con tu correo o con Google/GitHub.
3. Verifica el correo y entra al editor.
4. Ya estás listo: vas a importar/crear workflows desde **`Workflows → + Add workflow`** o **`Import from File`**.

> Alternativa self-hosted: `npx n8n` si quieres correrlo local. Para la práctica recomiendo Cloud, es cero fricción.

---

## 2. Groq — proveedor de modelos LLM (gratis)

1. Entra a **https://console.groq.com**.
2. **Sign in** con Google o GitHub.
3. Acepta los términos.
4. Ve a **API Keys → Create API Key**, ponle un nombre (ej: `n8n-demo`) y **copia la key** (empieza con `gsk_...`). Solo se muestra una vez.
5. Guárdala en un sitio temporal para pegarla luego en n8n.

> Modelos que vamos a usar: `qwen/qwen3-32b` y `openai/gpt-oss-120b`.

---

## 3. OpenRouter — segundo proveedor LLM (gratis)

1. Entra a **https://openrouter.ai**.
2. **Sign in** con Google o GitHub.
3. Ve a **Keys → Create Key**, ponle un nombre y **copia la key** (empieza con `sk-or-v1-...`).
4. Guárdala junto a la de Groq.

> Modelo gratis que vamos a usar: `openai/gpt-oss-120b:free`.

---

## 4. Hugging Face — para hostear el servicio Python (solo en una de las prácticas)

1. Entra a **https://huggingface.co/join** y crea cuenta con correo o Google.
2. Verifica el correo.
3. Ve a **Settings → Access Tokens → New token**, dale rol **`Write`** y **copia el token** (empieza con `hf_...`).
4. Guárdalo junto con las otras keys.

---

## 5. Configurar las credenciales en n8n

Una vez dentro de n8n Cloud:

1. Menú lateral → **Credentials → + Add credential**.
2. Crea **tres** credenciales (una por proveedor):
   - **Groq API** → pega la key `gsk_...`.
   - **OpenRouter API** → pega la key `sk-or-v1-...`.
   - **Hugging Face API** (si la práctica la pide) → pega el token `hf_...`.
3. Guarda. Ya las puedes seleccionar desde cualquier nodo del workflow.

---

## Checklist final antes de empezar

- [ ] Cuenta de n8n Cloud activa.
- [ ] Key de Groq copiada y registrada en n8n.
- [ ] Key de OpenRouter copiada y registrada en n8n.
- [ ] Token de Hugging Face copiado (si lo pide la práctica).
- [ ] Editor de n8n abierto en una pestaña.

Listo. Con eso ya puedes seguir la guía específica de cada práctica.
