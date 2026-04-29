"""
train_churn.py
================
Genera 2000 clientes sinteticos de una telco con features que SI predicen churn,
entrena un RandomForestClassifier y guarda los artefactos:

- customers.csv          -> dataset completo con email, customer_id y features
- churn_model.pkl        -> modelo entrenado
- feature_names.json     -> nombres y orden de las features (lo usa app.py)
- training_report.json   -> AUC, accuracy y feature importances

Incluye 4 perfiles HARDCODEADOS para la demo en vivo (ver tabla abajo).

Ejecucion:
    pip install -r requirements.txt
    python train_churn.py
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, accuracy_score, classification_report
from sklearn.model_selection import train_test_split

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
RANDOM_STATE = 42
N_CUSTOMERS = 2000
HERE = Path(__file__).parent

rng = np.random.default_rng(RANDOM_STATE)

# Features numericas: nombre -> (min, max, sesgo medio)
NUMERIC_FEATURES = [
    "tenure_months",
    "monthly_charge_usd",
    "total_charges_usd",
    "num_complaints_90d",
    "late_payments_12m",
    "support_calls_30d",
    "avg_data_usage_gb",
    "num_services",
    "discount_pct_active",
]

CATEGORICAL_FEATURES = [
    "contract_type",       # month_to_month / one_year / two_year
    "payment_method",      # electronic_check / credit_card / bank_transfer / cash
    "has_competitor_offer",# 0/1
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


# ---------------------------------------------------------------------------
# Generacion de datos sinteticos
# ---------------------------------------------------------------------------
def generate_synthetic_customers(n: int) -> pd.DataFrame:
    """Genera n clientes con distribuciones realistas y un target con senal."""

    tenure_months = rng.integers(1, 72, size=n)
    monthly_charge_usd = np.round(rng.normal(55, 22, size=n).clip(15, 150), 2)
    total_charges_usd = np.round(monthly_charge_usd * tenure_months * rng.uniform(0.85, 1.05, size=n), 2)

    num_complaints_90d = rng.poisson(0.4, size=n).clip(0, 8)
    late_payments_12m = rng.poisson(1.2, size=n).clip(0, 12)
    support_calls_30d = rng.poisson(0.6, size=n).clip(0, 10)

    avg_data_usage_gb = np.round(rng.gamma(shape=2.0, scale=12.0, size=n).clip(0, 200), 1)
    num_services = rng.integers(1, 6, size=n)
    discount_pct_active = np.round(rng.choice([0, 0, 0, 5, 10, 15, 20], size=n), 0)

    contract_type = rng.choice(
        ["month_to_month", "one_year", "two_year"],
        size=n,
        p=[0.55, 0.25, 0.20],
    )
    payment_method = rng.choice(
        ["electronic_check", "credit_card", "bank_transfer", "cash"],
        size=n,
        p=[0.35, 0.35, 0.20, 0.10],
    )
    has_competitor_offer = rng.choice([0, 1], size=n, p=[0.7, 0.3])

    # Campos extra de negocio (NO entran al modelo, los usan los agentes Comercial y CX)
    plan_type = np.where(
        monthly_charge_usd < 40, "basic",
        np.where(monthly_charge_usd < 80, "standard",
                 np.where(monthly_charge_usd < 110, "premium", "enterprise"))
    )
    # current_debt: solo morosos cronicos arrastran deuda
    current_debt_usd = np.where(
        late_payments_12m >= 3,
        np.round(monthly_charge_usd * rng.uniform(1.0, 3.0, size=n), 2),
        0.0,
    )
    preferred_channel = rng.choice(
        ["chat", "email", "phone", "whatsapp"],
        size=n,
        p=[0.4, 0.2, 0.15, 0.25],
    )
    last_complaint_text = np.where(
        num_complaints_90d > 0,
        rng.choice([
            "Internet inestable en horas pico",
            "Cobro duplicado en factura",
            "Demoras al contestar en el call center",
            "Velocidad menor a la contratada",
            "Cargo por servicio que no solicite",
        ], size=n),
        "sin quejas registradas",
    )

    df = pd.DataFrame({
        "tenure_months": tenure_months,
        "monthly_charge_usd": monthly_charge_usd,
        "total_charges_usd": total_charges_usd,
        "num_complaints_90d": num_complaints_90d,
        "late_payments_12m": late_payments_12m,
        "support_calls_30d": support_calls_30d,
        "avg_data_usage_gb": avg_data_usage_gb,
        "num_services": num_services,
        "discount_pct_active": discount_pct_active,
        "contract_type": contract_type,
        "payment_method": payment_method,
        "has_competitor_offer": has_competitor_offer,
        # Campos de negocio (no van al modelo)
        "plan_type": plan_type,
        "current_debt_usd": current_debt_usd,
        "preferred_channel": preferred_channel,
        "last_complaint_text": last_complaint_text,
    })

    # ----- Generar target con senal real -----
    # Logit base: combinacion lineal con buena senal
    logit = (
        -2.2
        - 0.07 * df["tenure_months"]                           # mas tenure -> menos churn (mas fuerte)
        + 0.025 * df["monthly_charge_usd"]                     # cobro alto -> mas churn
        + 0.55 * df["num_complaints_90d"]                      # quejas -> mas churn
        + 0.40 * df["late_payments_12m"]                       # atrasos -> mas churn
        + 0.30 * df["support_calls_30d"]                       # llamadas -> mas churn
        - 0.012 * df["avg_data_usage_gb"]                      # uso alto -> menos churn
        - 0.35 * df["num_services"]                            # mas servicios -> menos churn
        + 2.0 * df["has_competitor_offer"]                     # competencia -> mucho mas churn
        + (df["contract_type"] == "month_to_month").astype(int) * 1.6
        - (df["contract_type"] == "two_year").astype(int) * 1.4
        + (df["payment_method"] == "electronic_check").astype(int) * 0.6
        + 0.04 * df["discount_pct_active"]                     # descuento alto activo -> riesgo (post-discount)
    )
    # Ruido moderado para que no sea perfecto pero si separable
    logit += rng.normal(0, 0.35, size=n)
    prob = 1 / (1 + np.exp(-logit))
    churn = (rng.uniform(0, 1, size=n) < prob).astype(int)
    df["churn"] = churn

    # ----- Asignar IDs y emails sinteticos -----
    df.insert(0, "customer_id", np.arange(1, n + 1))
    df.insert(1, "name", [f"Cliente {i}" for i in df["customer_id"]])
    df.insert(2, "email", [f"user{i}@demo.com" for i in df["customer_id"]])

    return df


def inject_demo_profiles(df: pd.DataFrame) -> pd.DataFrame:
    """Sobrescribe 4 filas con perfiles deterministas para la demo en vivo."""

    profiles = [
        # ---- 1042: Premium fiel con oferta de competencia -> retain_aggressive
        {
            "customer_id": 1042,
            "name": "Ana Premium",
            "email": "ana.premium@demo.com",
            "tenure_months": 48,
            "monthly_charge_usd": 89.0,
            "total_charges_usd": 89.0 * 48,
            "num_complaints_90d": 0,
            "late_payments_12m": 0,
            "support_calls_30d": 0,
            "avg_data_usage_gb": 85.0,
            "num_services": 5,
            "discount_pct_active": 0,
            "contract_type": "two_year",
            "payment_method": "credit_card",
            "has_competitor_offer": 1,
            "plan_type": "premium",
            "current_debt_usd": 0.0,
            "preferred_channel": "email",
            "last_complaint_text": "sin quejas registradas",
            "churn": 0,
        },
        # ---- 2017: Cliente toxico, mal pagador -> let_go
        {
            "customer_id": 2017,
            "name": "Carlos Moroso",
            "email": "carlos.toxico@demo.com",
            "tenure_months": 14,
            "monthly_charge_usd": 65.0,
            "total_charges_usd": 65.0 * 14,
            "num_complaints_90d": 5,
            "late_payments_12m": 8,
            "support_calls_30d": 6,
            "avg_data_usage_gb": 12.0,
            "num_services": 2,
            "discount_pct_active": 10,
            "contract_type": "month_to_month",
            "payment_method": "electronic_check",
            "has_competitor_offer": 1,
            "plan_type": "standard",
            "current_debt_usd": 195.0,
            "preferred_channel": "phone",
            "last_complaint_text": "Cobro por servicio que nunca solicite, exigi reverso",
            "churn": 1,
        },
        # ---- 3088: Riesgo medio, no usa -> retain_soft (pausa)
        {
            "customer_id": 3088,
            "name": "Maria Inactiva",
            "email": "maria.inactiva@demo.com",
            "tenure_months": 22,
            "monthly_charge_usd": 49.0,
            "total_charges_usd": 49.0 * 22,
            "num_complaints_90d": 0,
            "late_payments_12m": 1,
            "support_calls_30d": 0,
            "avg_data_usage_gb": 3.5,
            "num_services": 2,
            "discount_pct_active": 0,
            "contract_type": "month_to_month",
            "payment_method": "credit_card",
            "has_competitor_offer": 0,
            "plan_type": "standard",
            "current_debt_usd": 0.0,
            "preferred_channel": "whatsapp",
            "last_complaint_text": "sin quejas registradas",
            "churn": 0,
        },
        # ---- 5001: Daniel (UPB) - cliente VIP en riesgo, perfecto para showcase
        {
            "customer_id": 5001,
            "name": "Daniel Hoyos Gonzalez",
            "email": "daniel.hoyosg@upb.edu.co",
            "tenure_months": 18,
            "monthly_charge_usd": 120.0,
            "total_charges_usd": 120.0 * 18,
            "num_complaints_90d": 4,
            "late_payments_12m": 0,
            "support_calls_30d": 6,
            "avg_data_usage_gb": 140.0,
            "num_services": 4,
            "discount_pct_active": 0,
            "contract_type": "month_to_month",
            "payment_method": "credit_card",
            "has_competitor_offer": 1,
            "plan_type": "premium",
            "current_debt_usd": 0.0,
            "preferred_channel": "chat",
            "last_complaint_text": "Velocidad de internet menor a la contratada en horario laboral",
            "churn": 1,
        },
        # ---- 7001: Pedro Moroso - cliente con deuda activa, plan basico, quiere mantener servicio -> escalate_human / plan de pagos
        {
            "customer_id": 7001,
            "name": "Pedro Moroso",
            "email": "pedro.moroso@demo.com",
            "tenure_months": 18,
            "monthly_charge_usd": 35.0,
            "total_charges_usd": 35.0 * 18,
            "num_complaints_90d": 1,
            "late_payments_12m": 4,
            "support_calls_30d": 3,
            "avg_data_usage_gb": 22.0,
            "num_services": 2,
            "discount_pct_active": 0,
            "contract_type": "month_to_month",
            "payment_method": "cash",
            "has_competitor_offer": 0,
            "plan_type": "basic",
            "current_debt_usd": 105.0,
            "preferred_channel": "whatsapp",
            "last_complaint_text": "Perdi el trabajo, no he podido pagar pero necesito el servicio",
            "churn": 1,
        },
    ]

    for profile in profiles:
        cid = profile["customer_id"]
        # Asegurar que el customer_id existe
        if cid not in df["customer_id"].values:
            # Agregar fila nueva
            new_row = {col: profile.get(col, df[col].iloc[0]) for col in df.columns}
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        else:
            for col, val in profile.items():
                df.loc[df["customer_id"] == cid, col] = val

    return df


# ---------------------------------------------------------------------------
# Encoding categorico simple (one-hot manual para reproducibilidad)
# ---------------------------------------------------------------------------
CONTRACT_LEVELS = ["month_to_month", "one_year", "two_year"]
PAYMENT_LEVELS = ["electronic_check", "credit_card", "bank_transfer", "cash"]


def encode_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df[NUMERIC_FEATURES].copy()
    for lvl in CONTRACT_LEVELS:
        out[f"contract_{lvl}"] = (df["contract_type"] == lvl).astype(int)
    for lvl in PAYMENT_LEVELS:
        out[f"payment_{lvl}"] = (df["payment_method"] == lvl).astype(int)
    out["has_competitor_offer"] = df["has_competitor_offer"].astype(int)
    return out


# ---------------------------------------------------------------------------
# Entrenamiento
# ---------------------------------------------------------------------------
def train_and_save() -> None:
    print(">> Generando datos sinteticos...")
    df = generate_synthetic_customers(N_CUSTOMERS)
    df = inject_demo_profiles(df)
    print(f"   total clientes: {len(df)} | churn rate: {df['churn'].mean():.2%}")

    X = encode_features(df)
    y = df["churn"]
    feature_names = X.columns.tolist()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_STATE, stratify=y
    )

    print(">> Entrenando RandomForestClassifier...")
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=10,
        n_jobs=-1,
        random_state=RANDOM_STATE,
        class_weight="balanced",
    )
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.5).astype(int)
    auc = roc_auc_score(y_test, proba)
    acc = accuracy_score(y_test, pred)
    print(f"   AUC test: {auc:.4f}")
    print(f"   ACC test: {acc:.4f}")
    print(classification_report(y_test, pred, target_names=["stay", "churn"]))

    importances = sorted(
        zip(feature_names, model.feature_importances_),
        key=lambda kv: kv[1],
        reverse=True,
    )
    print(">> Top 8 importancias:")
    for name, imp in importances[:8]:
        print(f"   {name:32s} {imp:.4f}")

    # ---- Guardar artefactos ----
    out_csv = HERE / "customers.csv"
    out_model = HERE / "churn_model.pkl"
    out_features = HERE / "feature_names.json"
    out_report = HERE / "training_report.json"

    df.to_csv(out_csv, index=False)
    joblib.dump(model, out_model)
    out_features.write_text(json.dumps(feature_names, indent=2))
    out_report.write_text(json.dumps({
        "auc": auc,
        "accuracy": acc,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "feature_importances": dict(importances),
    }, indent=2))

    print()
    print(f">> Guardado: {out_csv.name}, {out_model.name}, {out_features.name}, {out_report.name}")
    print(">> Listo. Ahora corre: uvicorn app:app --reload --port 8000")


if __name__ == "__main__":
    train_and_save()
