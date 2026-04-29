---
title: Churn MCP Demo
emoji: 🛡️
colorFrom: purple
colorTo: blue
sdk: docker
pinned: false
license: mit
---

# Churn Retention MCP Demo

FastAPI service que expone un modelo de **churn (Random Forest)** como **REST + tools MCP**.

Construido para la clase demo de la **Maestría en Ciencia de Datos — UPB Virtual**
(29 abril 2026, ponente: *Daniel Hoyos González*).

## Endpoints clave

| Método | Ruta                       | Descripción                              |
|--------|----------------------------|------------------------------------------|
| GET    | `/docs`                    | Swagger UI                               |
| GET    | `/health`                  | Healthcheck                              |
| GET    | `/customer/by-email`       | Lookup por correo                        |
| GET    | `/customer/{id}`           | Lookup por id                            |
| GET    | `/payments/{id}`           | Histórico de pagos sintético             |
| POST   | `/predict_churn`           | Probabilidad + drivers + sugerencia      |
| GET    | `/mcp/tools`               | Descriptor estilo Model Context Protocol |
| POST   | `/mcp/invoke`              | Ejecuta tool por nombre                  |

## Clientes hardcodeados para la demo

| Email                          | id   | Resultado esperado |
|--------------------------------|------|--------------------|
| `ana.premium@demo.com`         | 1042 | retain_aggressive  |
| `carlos.toxico@demo.com`       | 2017 | let_go             |
| `maria.inactiva@demo.com`      | 3088 | retain_soft        |
| `daniel.hoyosg@upb.edu.co`     | 5001 | retain_aggressive (showcase VIP) |
