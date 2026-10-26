FROM python:3.12-slim

WORKDIR /app

# Copiar os requisitos e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o código fonte
COPY . .

# Arrancar o FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]