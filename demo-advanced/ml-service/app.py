"""
app.py
======
Servicio FastAPI + servidor MCP para la demo multi-agente.

Expone 4 herramientas MCP, una por agente:

  Concierge   -> lookup_customer(email)
  Comercial   -> get_payment_history(email)         # info de plan, pagos, mora, deuda
  Riesgo      -> predict_churn_risk(email)          # modelo ML real
  CX          -> get_support_history(email)         # info cruda de soporte (sin scores)

Endpoints:
  REST tradicional:
      GET  /                                # info
      GET  /health                          # sanity check
      GET  /customer/by-email?email=...     # debug rapido
      POST /predict_churn                   # debug del modelo
  MCP (streamable HTTP, compatible con n8n MCP Client Tool):
      ALL  /mcp                             # endpoint MCP unico

Local:
    uvicorn app:app --reload --port 8000

HF Spaces:
    Dockerfile expone 7860.
"""

from __future__ import annotations

import hashlib
import json
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from pydantic import BaseModel, Field

HERE = Path(__file__).parent

# ---------------------------------------------------------------------------
# Carga de artefactos del modelo
# ---------------------------------------------------------------------------
MODEL_PATH = HERE / "churn_model.pkl"
CUSTOMERS_PATH = HERE / "customers.csv"
FEATURES_PATH = HERE / "feature_names.json"

if not MODEL_PATH.exists():
    raise RuntimeError(
        "No se encontro churn_model.pkl. Ejecuta primero:  python train_churn.py"
    )

MODEL = joblib.load(MODEL_PATH)
CUSTOMERS = pd.read_csv(CUSTOMERS_PATH)
FEATURE_NAMES: list[str] = json.loads(FEATURES_PATH.read_text())

CONTRACT_LEVELS = ["month_to_month", "one_year", "two_year"]
PAYMENT_LEVELS = ["electronic_check", "credit_card", "bank_transfer", "cash"]
NUMERIC_FEATURES = [
    "tenure_months", "monthly_charge_usd", "total_charges_usd",
    "num_complaints_90d", "late_payments_12m", "support_calls_30d",
    "avg_data_usage_gb", "num_services", "discount_pct_active",
]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _find_by_email(email: str) -> pd.Series:
    match = CUSTOMERS[CUSTOMERS["email"].str.lower() == email.lower().strip()]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Cliente no encontrado: {email}")
    return match.iloc[0]


def _row_to_feature_vector(row: pd.Series) -> np.ndarray:
    feat = {f: float(row[f]) for f in NUMERIC_FEATURES}
    for lvl in CONTRACT_LEVELS:
        feat[f"contract_{lvl}"] = int(row["contract_type"] == lvl)
    for lvl in PAYMENT_LEVELS:
        feat[f"payment_{lvl}"] = int(row["payment_method"] == lvl)
    feat["has_competitor_offer"] = int(row["has_competitor_offer"])
    return np.array([[feat[name] for name in FEATURE_NAMES]])


def _top_drivers(row: pd.Series, k: int = 3) -> list[dict[str, Any]]:
    vec = _row_to_feature_vector(row)[0]
    importances = MODEL.feature_importances_
    means = CUSTOMERS[NUMERIC_FEATURES].mean()
    stds = CUSTOMERS[NUMERIC_FEATURES].std().replace(0, 1)
    contributions = []
    for name, val, imp in zip(FEATURE_NAMES, vec, importances):
        if name in NUMERIC_FEATURES:
            z = abs((val - means[name]) / stds[name])
        else:
            z = abs(val)
        contributions.append({
            "feature": name,
            "value": round(float(val), 3),
            "importance": round(float(imp), 4),
            "weighted_score": round(float(imp * z), 4),
        })
    contributions.sort(key=lambda d: d["weighted_score"], reverse=True)
    return contributions[:k]


def _generate_payments(customer_id: int, row: pd.Series) -> list[dict[str, Any]]:
    seed = int(hashlib.md5(str(customer_id).encode()).hexdigest(), 16) % (2**32)
    rng_local = random.Random(seed)
    base = float(row["monthly_charge_usd"])
    late_total = int(row["late_payments_12m"])
    payments = []
    today = datetime(2026, 4, 27)
    for i in range(12):
        date = today - timedelta(days=30 * (i + 1))
        is_late = i < late_total
        amount = round(base * rng_local.uniform(0.95, 1.05), 2)
        payments.append({
            "month": date.strftime("%Y-%m"),
            "amount_usd": amount,
            "status": "late" if is_late else "on_time",
            "days_late": rng_local.randint(5, 30) if is_late else 0,
        })
    payments.reverse()
    return payments


# ---------------------------------------------------------------------------
# Logica de las 4 tools (separada para reuso REST + MCP)
# ---------------------------------------------------------------------------
def _tool_lookup_customer(email: str) -> dict[str, Any]:
    """Concierge: identifica al cliente, datos basicos."""
    row = _find_by_email(email)
    return {
        "customer_id": int(row["customer_id"]),
        "name": str(row["name"]),
        "email": str(row["email"]),
        "plan_type": str(row["plan_type"]),
        "tenure_months": int(row["tenure_months"]),
        "preferred_channel": str(row["preferred_channel"]),
    }


def _tool_get_payment_history(email: str) -> dict[str, Any]:
    """Comercial: pagos, mora, deuda actual, plan, ingreso lifetime."""
    row = _find_by_email(email)
    cid = int(row["customer_id"])
    payments = _generate_payments(cid, row)
    on_time = sum(1 for p in payments if p["status"] == "on_time")
    late = len(payments) - on_time
    return {
        "customer_id": cid,
        "name": str(row["name"]),
        "plan_type": str(row["plan_type"]),
        "monthly_charge_usd": float(row["monthly_charge_usd"]),
        "total_lifetime_revenue_usd": float(row["total_charges_usd"]),
        "current_debt_usd": float(row["current_debt_usd"]),
        "in_collections": bool(float(row["current_debt_usd"]) > 0),
        "payment_method": str(row["payment_method"]),
        "discount_pct_active": float(row["discount_pct_active"]),
        "summary_12m": {
            "on_time_payments": on_time,
            "late_payments": late,
            "on_time_pct": round(on_time / len(payments), 3),
            "avg_ticket_usd": round(float(np.mean([p["amount_usd"] for p in payments])), 2),
        },
        "last_12_payments": payments,
    }


def _tool_predict_churn_risk(email: str) -> dict[str, Any]:
    """Riesgo: modelo ML de churn."""
    row = _find_by_email(email)
    vec = _row_to_feature_vector(row)
    prob = float(MODEL.predict_proba(vec)[0, 1])
    risk_level = "high" if prob >= 0.65 else "medium" if prob >= 0.4 else "low"
    drivers = _top_drivers(row, k=3)
    return {
        "customer_id": int(row["customer_id"]),
        "name": str(row["name"]),
        "churn_probability": round(prob, 4),
        "risk_level": risk_level,
        "top_drivers": drivers,
        "model_signals": {
            "tenure_months": int(row["tenure_months"]),
            "has_competitor_offer": bool(int(row["has_competitor_offer"])),
            "contract_type": str(row["contract_type"]),
            "late_payments_12m": int(row["late_payments_12m"]),
            "num_complaints_90d": int(row["num_complaints_90d"]),
        },
    }


def _tool_get_support_history(email: str) -> dict[str, Any]:
    """CX: info cruda de soporte y experiencia (SIN scores)."""
    row = _find_by_email(email)
    return {
        "customer_id": int(row["customer_id"]),
        "name": str(row["name"]),
        "preferred_channel": str(row["preferred_channel"]),
        "num_complaints_90d": int(row["num_complaints_90d"]),
        "support_calls_30d": int(row["support_calls_30d"]),
        "last_complaint_text": str(row["last_complaint_text"]),
        "avg_data_usage_gb": float(row["avg_data_usage_gb"]),
        "num_services_active": int(row["num_services"]),
        "tenure_months": int(row["tenure_months"]),
    }


# ---------------------------------------------------------------------------
# Servidor MCP (FastMCP)
# ---------------------------------------------------------------------------
mcp = FastMCP("Customer Retention MCP")


@mcp.tool
def lookup_customer(email: str) -> dict:
    """
    [Concierge Agent] Identifica al cliente por su correo.
    Devuelve: customer_id, name, email, plan_type (basic|standard|premium|enterprise),
    tenure_months y preferred_channel.
    Devuelve error si el correo no existe.
    """
    return _tool_lookup_customer(email)


@mcp.tool
def get_payment_history(email: str) -> dict:
    """
    [Comercial / Pagos Agent] Devuelve la informacion comercial y de pagos del cliente:
    plan_type, monthly_charge_usd, total_lifetime_revenue_usd, current_debt_usd,
    in_collections (bool), payment_method, descuento activo,
    resumen 12 meses (pagos a tiempo/atrasados, % cumplimiento, ticket promedio)
    y la lista detallada de los ultimos 12 pagos.
    Sirve para evaluar valor del cliente y comportamiento de pago.
    """
    return _tool_get_payment_history(email)


@mcp.tool
def predict_churn_risk(email: str) -> dict:
    """
    [Riesgo / Churn Agent] Llama al modelo de machine learning entrenado (RandomForest)
    y devuelve: churn_probability (0-1), risk_level (low|medium|high),
    top_drivers (top 3 features que explican la prediccion) y los model_signals
    crudos que mas pesan (tenure, contrato, oferta competencia, atrasos, quejas).
    """
    return _tool_predict_churn_risk(email)


@mcp.tool
def get_support_history(email: str) -> dict:
    """
    [CX / Experiencia Agent] Devuelve informacion CRUDA de la experiencia del cliente
    con soporte (sin scores ni clasificaciones):
    preferred_channel, num_complaints_90d, support_calls_30d,
    last_complaint_text (texto literal), avg_data_usage_gb,
    num_services_active y tenure_months.
    Permite al agente CX juzgar tono, urgencia y canal apropiado.
    """
    return _tool_get_support_history(email)


# Construir la app ASGI del MCP (streamable HTTP, transporte recomendado)
mcp_app = mcp.http_app(path="/")


# ---------------------------------------------------------------------------
# FastAPI (REST + montaje del MCP en /mcp)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp_app.lifespan(_app):
        yield


app = FastAPI(
    title="Customer Retention MCP Demo",
    description=(
        "Demo multi-agente para la Maestria en Ciencia de Datos UPB. "
        "Expone un servidor MCP en /mcp con 4 tools: "
        "lookup_customer, get_payment_history, predict_churn_risk, get_support_history."
    ),
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PredictRequest(BaseModel):
    email: str = Field(..., examples=["daniel.hoyosg@upb.edu.co"])


@app.get("/")
def root():
    return {
        "service": "customer-retention-mcp",
        "version": "2.0.0",
        "docs": "/docs",
        "mcp_endpoint": "/mcp/",
        "mcp_transport": "streamable-http",
        "mcp_tools": [
            "lookup_customer",
            "get_payment_history",
            "predict_churn_risk",
            "get_support_history",
        ],
        "rest_debug": [
            "/health",
            "/customer/by-email?email=...",
            "POST /predict_churn  body: {email}",
            "/payment_history?email=...",
            "/support_history?email=...",
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": True, "customers": int(len(CUSTOMERS))}


# Endpoints REST de debug (espejo de las tools MCP, mismo input por email)
@app.get("/customer/by-email")
def rest_lookup(email: str = Query(...)):
    return _tool_lookup_customer(email)


@app.get("/payment_history")
def rest_payments(email: str = Query(...)):
    return _tool_get_payment_history(email)


@app.post("/predict_churn")
def rest_predict(payload: PredictRequest):
    return _tool_predict_churn_risk(payload.email)


@app.get("/support_history")
def rest_support(email: str = Query(...)):
    return _tool_get_support_history(email)


# Montar el servidor MCP en /mcp (n8n MCP Client Tool apunta aqui)
app.mount("/mcp", mcp_app)
