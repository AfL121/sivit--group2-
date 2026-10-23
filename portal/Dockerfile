FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# requirements primeiro: o pip install fica em cache enquanto as dependências
# não mudarem, e o código muda a toda a hora (ver TP1-E1).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x arranque.sh
EXPOSE 8000
CMD ["./arranque.sh"]
