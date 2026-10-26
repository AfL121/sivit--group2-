import asyncio
import json
import os
import sys
import time
from datetime import datetime
import asyncpg
import aio_pika

async def process_message(message: aio_pika.IncomingMessage, pool, ack_automatico, morrer_antes_do_ack):
    agora = time.time()
    
    try:
        corpo = json.loads(message.body.decode())
    except Exception:
        if not ack_automatico:
            await message.reject(requeue=False)
        return
        
    publicado_em = corpo.get("_publicado_em")
    latencia_ms = (agora - datetime.fromisoformat(publicado_em).timestamp()) * 1000 if publicado_em else 0.0

    try:
        # Lógica futura do TP1: Enviar para WebSockets ou Cache para o painel em tempo real
                
        if morrer_antes_do_ack == 1:
            sys.exit(1)
            
        if not ack_automatico:
            await message.ack()
            
        print(json.dumps({
            "evento": "processado", "ts": agora, "fila": "display",
            "latencia_ms": latencia_ms, "id": message.message_id
        }), flush=True)

    except Exception as e:
        print(f"ERRO AO PROCESSAR: {e}", flush=True)
        if not ack_automatico:
            await message.reject(requeue=False)

async def main():
    amqp_url = os.environ.get("AMQP_URL", "amqp://sivit:devpass@broker:5672/")
    db_url = os.environ.get("DATABASE_URL", "postgresql://sivit:devpass@sivitDB:5432/sivit")
    prefetch = int(os.environ.get("PREFETCH", 10))
    ack_automatico = int(os.environ.get("ACK_AUTOMATICO", 0))
    morrer_apos = int(os.environ.get("MORRER_APOS", 0))
    morrer_antes_do_ack = int(os.environ.get("MORRER_ANTES_DO_ACK", 0))
    max_mensagens = int(os.environ.get("MAX_MENSAGENS", 100000))
    politica_cheia = os.environ.get("POLITICA_CHEIA", "reject-publish")

    pool = await asyncpg.create_pool(db_url)
    connection = await aio_pika.connect_robust(amqp_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=prefetch)

    exchange = await channel.declare_exchange("leituras", aio_pika.ExchangeType.TOPIC, durable=True)
    dlx = await channel.declare_exchange("leituras.dlx", aio_pika.ExchangeType.DIRECT, durable=True)

    dlq = await channel.declare_queue("display.dlq", durable=True)
    await dlq.bind(dlx, routing_key="display")

    args = {
        "x-dead-letter-exchange": "leituras.dlx",
        "x-dead-letter-routing-key": "display",
        "x-max-length": max_mensagens,
        "x-overflow": politica_cheia
    }
    queue = await channel.declare_queue("display", durable=True, arguments=args)
    await queue.bind(exchange, routing_key="leitura.#")

    count = 0
    async with queue.iterator(no_ack=bool(ack_automatico)) as queue_iter:
        async for message in queue_iter:
            await process_message(message, pool, ack_automatico, morrer_antes_do_ack)
            count += 1
            if morrer_apos > 0 and count >= morrer_apos:
                sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())