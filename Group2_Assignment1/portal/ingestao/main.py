import json
import asyncio
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import asyncpg
import aio_pika
import os
import httpx
from fastapi import FastAPI, Response, status, HTTPException
from pydantic import BaseModel

class Reading(BaseModel):
    dispositivo: str
    instante: datetime
    parametro: str
    valor: float
    unidade: str

PORTAL_URL = "http://portal:8000"

falhas_consecutivas = 0
MAX_FALHAS = 3
ABERTO_ATE = 0
cache_dispositivos = {}
TTL_CACHE = 60.0

async def validate_device(serial: str) -> bool:
    global falhas_consecutivas, ABERTO_ATE, cache_dispositivos
    agora = time.time()
    
    if serial in cache_dispositivos and cache_dispositivos[serial] > agora:
        return True
    if agora < ABERTO_ATE:
        return True
        
    try:
        async with httpx.AsyncClient(timeout=0.5) as cli:
            r = await cli.get(f"{PORTAL_URL}/api/v1/devices/{serial}/")
            falhas_consecutivas = 0 
            valido = r.status_code == 200 and r.json().get("admission") is not None
            if valido:
                cache_dispositivos[serial] = agora + TTL_CACHE
            return valido
    except Exception:
        falhas_consecutivas += 1
        if falhas_consecutivas >= MAX_FALHAS:
            ABERTO_ATE = agora + 10.0
        return True

pool = None
broker_conn = None
exchange = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, broker_conn, exchange
    
    # 1. Ligação BD (Mantida para testes POR_FILA=0)
    db_url = os.getenv("DATABASE_URL", "postgresql://sivit:sivit@sivitDB:5432/sivit")
    pool = await asyncpg.create_pool(db_url)
    
    # 2. Ligação RabbitMQ (TP5)
    amqp_url = os.environ.get("AMQP_URL", "amqp://sivit:devpass@broker:5672/")
    broker_conn = await aio_pika.connect_robust(amqp_url)
    # Exercício 1: Ativar/Desativar publisher confirms na criação do canal
    usa_confirms = bool(int(os.environ.get("CONFIRMS", 1)))
    channel = await broker_conn.channel(publisher_confirms=usa_confirms)
        
    # Declarar o tópico 'leituras' durável
    exchange = await channel.declare_exchange("leituras", aio_pika.ExchangeType.TOPIC, durable=True)
    
    yield
    
    await pool.close()
    await broker_conn.close()

app = FastAPI(lifespan=lifespan)

# Função nova que encapsula a lógica de formatação e publicação
async def publish(r: Reading):
    body = r.model_dump(mode="json")
    # Regra TP5: adicionar _publicado_em em ISO 8601 com timezone
    body["_publicado_em"] = datetime.now(timezone.utc).isoformat()
    
    mensagem = aio_pika.Message(
        body=json.dumps(body).encode(),
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        # Chave de desduplicação
        message_id=f"{r.dispositivo}|{r.instante.isoformat()}|{r.parametro}"
    )
    # Ex: leitura.fc.SN-0001
    routing_key = f"leitura.{r.parametro.lower()}.{r.dispositivo}"
    
    await exchange.publish(mensagem, routing_key=routing_key)

@app.post("/v1/leituras", status_code=202)
async def ingest(batch: list[Reading]):
    global pool
    
    for r in batch:
        try:
            await validate_device(r.dispositivo)
        except Exception as e:
            print(f"Erro ao ligar ao portal: {e}")
            
    # Lógica condicional imposta pelas variáveis de ambiente de TP5
    por_fila = int(os.environ.get("POR_FILA", 1))
    
    if por_fila == 0:
        # Comportamento antigo TP4 (para a coluna "Sem fila" do relatório)
        rows = [(r.dispositivo, r.instante, r.parametro, r.valor, r.unidade) for r in batch]
        async with pool.acquire() as c:
            await c.executemany("""
            INSERT INTO vigilancia_leitura
            (dispositivo_id, instante, parametro, valor, unidade)
            VALUES (
                (SELECT id FROM vigilancia_dispositivo WHERE numero_serie = $1), 
                $2, $3, $4, $5
            )
            ON CONFLICT (dispositivo_id, instante, parametro) DO NOTHING
            """, rows)
    else:
        # Novo comportamento TP5
        try:
            await asyncio.gather(*(publish(r) for r in batch))
        except Exception:
            # Ex. 4.1: SPOF do broker
            raise HTTPException(503, detail="broker indisponivel")
            
    return {"received": len(batch)}

@app.get("/health/live")
def live():
    return {"status": "ok"}

# O guião testa a disponibilidade com /saude/pronto, adicionei a rota alias
@app.get("/saude/pronto")
@app.get("/health/ready")
async def ready(response: Response):
    global pool, broker_conn
    por_fila = int(os.environ.get("POR_FILA", 1))
    
    try:
        if por_fila == 0:
            async with pool.acquire() as c:
                await c.execute("SELECT 1")
        else:
            if broker_conn is None or broker_conn.is_closed:
                raise Exception("Broker fechado")
        return {"estado": "pronto"}
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"detail": "broker indisponivel" if por_fila else "database unavailable"}