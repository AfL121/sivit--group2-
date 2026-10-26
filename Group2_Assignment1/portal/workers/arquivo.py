import asyncio
import json
import os
import sys
import time
from datetime import datetime
import asyncpg
import aio_pika

async def process_message(message: aio_pika.IncomingMessage, pool, ack_automatico, sem_on_conflict, morrer_antes_do_ack):
    agora = time.time()
    
    # 1. Parse da mensagem
    try:
        corpo = json.loads(message.body.decode())
    except Exception:
        if not ack_automatico:
            await message.reject(requeue=False) # Vai para a DLQ
        return
        
    dispositivo = corpo.get("dispositivo")
    instante = datetime.fromisoformat(corpo.get("instante")) if corpo.get("instante") else None
    parametro = corpo.get("parametro")
    valor = corpo.get("valor")
    unidade = corpo.get("unidade")
    publicado_em = corpo.get("_publicado_em")
    
    latencia_ms = (agora - datetime.fromisoformat(publicado_em).timestamp()) * 1000 if publicado_em else 0.0

    # 2. Inserção na Base de Dados (com lógica para os botões das experiências)
    try:
        async with pool.acquire() as conn:
            if sem_on_conflict == 1:
                # Exercício 3c: Forçar erro de duplicação tirando a proteção
                await conn.execute("""
                    INSERT INTO vigilancia_leitura (dispositivo_id, instante, parametro, valor, unidade)
                    VALUES ((SELECT id FROM vigilancia_dispositivo WHERE numero_serie = $1), $2, $3, $4, $5)
                """, dispositivo, instante, parametro, valor, unidade)
            else:
                # Fluxo normal idempotente
                await conn.execute("""
                    INSERT INTO vigilancia_leitura (dispositivo_id, instante, parametro, valor, unidade)
                    VALUES ((SELECT id FROM vigilancia_dispositivo WHERE numero_serie = $1), $2, $3, $4, $5)
                    ON CONFLICT (dispositivo_id, instante, parametro) DO NOTHING
                """, dispositivo, instante, parametro, valor, unidade)
                
        # Exercício 3c: Simular falha antes de confirmar
        if morrer_antes_do_ack == 1:
            sys.exit(1)
            
        # 3. ACK Manual e Registo de Log
        if not ack_automatico:
            await message.ack()
            
        # Log obrigatório para as ferramentas de medição
        print(json.dumps({
            "evento": "processado", "ts": agora, "fila": "arquivo",
            "latencia_ms": latencia_ms, "id": message.message_id
        }), flush=True)

    except Exception as e:
        print(f"ERRO AO PROCESSAR: {e}", flush=True)  # <--- COLOCAS O PRINT AQUI
        if not ack_automatico:
            await message.reject(requeue=False)

async def main():
    # LER VARIÁVEIS DE AMBIENTE
    amqp_url = os.environ.get("AMQP_URL", "amqp://sivit:devpass@broker:5672/")
    db_url = os.environ.get("DATABASE_URL", "postgresql://sivit:devpass@sivitDB:5432/sivit")
    prefetch = int(os.environ.get("PREFETCH", 10))
    ack_automatico = int(os.environ.get("ACK_AUTOMATICO", 0))
    sem_on_conflict = int(os.environ.get("SEM_ON_CONFLICT", 0))
    morrer_apos = int(os.environ.get("MORRER_APOS", 0))
    morrer_antes_do_ack = int(os.environ.get("MORRER_ANTES_DO_ACK", 0))
    max_mensagens = int(os.environ.get("MAX_MENSAGENS", 100000))
    politica_cheia = os.environ.get("POLITICA_CHEIA", "reject-publish")

    pool = await asyncpg.create_pool(db_url)
    connection = await aio_pika.connect_robust(amqp_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=prefetch)

    # DECLARAR EXCHANGE PRINCIPAL E DEAD-LETTER EXCHANGE
    exchange = await channel.declare_exchange("leituras", aio_pika.ExchangeType.TOPIC, durable=True)
    dlx = await channel.declare_exchange("leituras.dlx", aio_pika.ExchangeType.DIRECT, durable=True)

    # DECLARAR DEAD-LETTER QUEUE
    dlq = await channel.declare_queue("arquivo.dlq", durable=True)
    await dlq.bind(dlx, routing_key="arquivo")

    # DECLARAR FILA PRINCIPAL COM LIMITES E ROTEAMENTO PARA DLQ
    args = {
        "x-dead-letter-exchange": "leituras.dlx",
        "x-dead-letter-routing-key": "arquivo",
        "x-max-length": max_mensagens,
        "x-overflow": politica_cheia
    }
    queue = await channel.declare_queue("arquivo", durable=True, arguments=args)
    await queue.bind(exchange, routing_key="leitura.#")

    count = 0
    async with queue.iterator(no_ack=bool(ack_automatico)) as queue_iter:
        async for message in queue_iter:
            await process_message(message, pool, ack_automatico, sem_on_conflict, morrer_antes_do_ack)
            count += 1
            if morrer_apos > 0 and count >= morrer_apos:
                sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())