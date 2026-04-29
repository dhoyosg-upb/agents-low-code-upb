FROM python:3.11-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Entrenar el modelo durante el build (genera churn_model.pkl, customers.csv, etc.)
RUN python train_churn.py

# Hugging Face Spaces espera el puerto 7860
EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
