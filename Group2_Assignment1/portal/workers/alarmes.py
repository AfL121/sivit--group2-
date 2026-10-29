import asyncio
import json
import os
import sys
import time
from datetime import datetime
import asyncpg
import aio_pika
import math
import operator
from pathlib import Path


# Intervalo máximo permitido entre leituras consecutivas (segundos)
INTERVALO_MAXIMO = 5

OPERADORES = {
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge
}

def carregar_regras():
    caminho = Path(__file__).with_name("regras_alarmes.json")

    with open(caminho, "r", encoding="utf-8") as ficheiro:
        regras = json.load(ficheiro)

    return regras


def detetar_alarme(parametro, valor, regras):
    alarmes_detetados = []

    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return alarmes_detetados

    if not math.isfinite(valor):
        return alarmes_detetados

    for nome_regra, configuracao in regras.items():
        if configuracao["parametro"] != parametro:
            continue

        operador = OPERADORES[configuracao["operador"]]
        limite = configuracao["limite"]

        if operador(valor, limite):
            alarmes_detetados.append(nome_regra)

    return alarmes_detetados



async def obter_estado_alarme(conn, dispositivo, regra):
    return await conn.fetchrow("""
        SELECT
            ea.inicio_episodio,
            ea.ultimo_instante
        FROM vigilancia_estadoalarme ea
        JOIN vigilancia_dispositivo d
            ON ea.dispositivo_id = d.id
        WHERE d.numero_serie = $1
          AND ea.regra = $2
    """, dispositivo, regra)



async def criar_estado_alarme(conn, dispositivo, regra, instante):
    resultado = await conn.execute("""
        INSERT INTO vigilancia_estadoalarme
            (dispositivo_id, regra, inicio_episodio, ultimo_instante)
        SELECT
            d.id, $2, $3, $3
        FROM vigilancia_dispositivo d
        WHERE d.numero_serie = $1

        ON CONFLICT (dispositivo_id, regra)
        DO UPDATE SET
            inicio_episodio = EXCLUDED.inicio_episodio,
            ultimo_instante = EXCLUDED.ultimo_instante
        WHERE vigilancia_estadoalarme.inicio_episodio IS NULL
          AND vigilancia_estadoalarme.ultimo_instante < EXCLUDED.ultimo_instante
    """, dispositivo, regra, instante)

    if resultado == "INSERT 0 0":
        existe = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1
                FROM vigilancia_dispositivo
                WHERE numero_serie = $1
            )
        """, dispositivo)

        if not existe:
            raise ValueError(f"Dispositivo desconhecido: {dispositivo}")

    return resultado == "INSERT 0 1"


async def atualizar_estado_alarme(conn, dispositivo, regra, instante):
    resultado = await conn.execute("""
        UPDATE vigilancia_estadoalarme
        SET ultimo_instante = $3
        WHERE dispositivo_id = (
            SELECT id
            FROM vigilancia_dispositivo
            WHERE numero_serie = $1
        )
        AND regra = $2
        AND ultimo_instante < $3
    """, dispositivo, regra, instante)

    return resultado == "UPDATE 1"



async def terminar_estado_alarme(conn, dispositivo, regra, instante):
    resultado = await conn.execute("""
        UPDATE vigilancia_estadoalarme
        SET inicio_episodio = NULL,
            ultimo_instante = $3
        WHERE dispositivo_id = (
            SELECT id
            FROM vigilancia_dispositivo
            WHERE numero_serie = $1
        )
        AND regra = $2
        AND inicio_episodio IS NOT NULL
        AND ultimo_instante < $3
    """, dispositivo, regra, instante)

    return resultado == "UPDATE 1"


async def atualizar_instante_normal(conn, dispositivo, regra, instante):
    await conn.execute("""
        INSERT INTO vigilancia_estadoalarme
            (dispositivo_id, regra, inicio_episodio, ultimo_instante)
        SELECT
            d.id, $2, NULL, $3
        FROM vigilancia_dispositivo d
        WHERE d.numero_serie = $1

        ON CONFLICT (dispositivo_id, regra)
        DO UPDATE SET
            ultimo_instante = EXCLUDED.ultimo_instante
        WHERE vigilancia_estadoalarme.inicio_episodio IS NULL
          AND vigilancia_estadoalarme.ultimo_instante < EXCLUDED.ultimo_instante
    """, dispositivo, regra, instante)


async def resolver_alarme(conn, dispositivo, regra, inicio_episodio):
    chave = f"{regra}|{dispositivo}|{inicio_episodio.isoformat()}"

    resultado = await conn.execute("""
        UPDATE vigilancia_alarme
        SET estado = 'RESOLVIDO'
        WHERE chave = $1
          AND estado IN ('ATIVO', 'RECONHECIDO')
    """, chave)

    return resultado == "UPDATE 1"



def obter_regras_parametro(parametro, regras):
    return {
        nome: configuracao
        for nome, configuracao in regras.items()
        if configuracao["parametro"] == parametro
    }


async def processar_regra(conn, dispositivo, parametro, valor,
                         instante, nome_regra, configuracao):

    operador = OPERADORES[configuracao["operador"]]
    limite = configuracao["limite"]
    duracao = configuracao["duracao"]

    condicao_ativa = operador(valor, limite)

    # Consultar o episódio existente
    estado = await obter_estado_alarme(conn, dispositivo, nome_regra)
    # Ignorar leituras repetidas ou anteriores à última processada
    if estado is not None:
        ultimo_instante = estado["ultimo_instante"]

        if instante <= ultimo_instante:
            return None
                # Verificar se houve uma interrupção prolongada
        intervalo = (instante - ultimo_instante).total_seconds()



        if intervalo > INTERVALO_MAXIMO and condicao_ativa:
            # Verificar se o episódio já originou um alarme
            inicio_anterior = estado["inicio_episodio"]
            alarme_existente = False

            if inicio_anterior is not None:
                chave = f"{nome_regra}|{dispositivo}|{inicio_anterior.isoformat()}"

                alarme_existente = await conn.fetchval("""
                    SELECT EXISTS(
                        SELECT 1
                        FROM vigilancia_alarme
                        WHERE chave = $1
                          AND estado IN ('ATIVO', 'RECONHECIDO')
                    )
                """, chave)

            # Só reiniciar episódios que ainda não originaram alarmes
            if not alarme_existente:
                await conn.execute("""
                    UPDATE vigilancia_estadoalarme
                    SET inicio_episodio = NULL
                    WHERE dispositivo_id = (
                        SELECT id
                        FROM vigilancia_dispositivo
                        WHERE numero_serie = $1
                    )
                    AND regra = $2
                    AND ultimo_instante = $3
                """, dispositivo, nome_regra, ultimo_instante)

                estado = await obter_estado_alarme(
                    conn, dispositivo, nome_regra
                )


    if condicao_ativa:
        if estado is None or estado["inicio_episodio"] is None:

            criado = await criar_estado_alarme(
                conn, dispositivo, nome_regra, instante
            )

            if not criado:
                # Outro processamento já atualizou o estado
                return None

            inicio_episodio = instante


        else:
            # Leitura anómala durante um episódio existente
            inicio_episodio = estado["inicio_episodio"]

            await atualizar_estado_alarme(
                conn, dispositivo, nome_regra, instante
            )

        tempo_decorrido = (
            instante - inicio_episodio
        ).total_seconds()

        if tempo_decorrido > duracao or duracao == 0:
            return inicio_episodio



    else:
        # A leitura está dentro dos valores normais
        if estado is not None and estado["inicio_episodio"] is not None:

            # Terminar o episódio ativo
            terminou = await terminar_estado_alarme(
                conn, dispositivo, nome_regra, instante
            )

            if terminou:
                # Resolver o alarme clínico correspondente
                await resolver_alarme(
                    conn,
                    dispositivo,
                    nome_regra,
                    estado["inicio_episodio"]
                )

        else:
            # Não existe episódio ativo
            # Guardar o instante da leitura normal
            await atualizar_instante_normal(
                conn, dispositivo, nome_regra, instante
            )

    return None



async def guardar_alarme(conn, dispositivo, parametro, valor, regra, inicio_episodio):
    chave = f"{regra}|{dispositivo}|{inicio_episodio.isoformat()}"

    resultado = await conn.execute("""
        INSERT INTO vigilancia_alarme
            (chave, dispositivo_id, internamento_id, regra,
             parametro, valor, mensagem, estado, criado_em)
        SELECT
            $1,
            d.id,
            d.internamento_id,
            $2,
            $3,
            $4,
            $5,
            'ATIVO',
            NOW()
        FROM vigilancia_dispositivo d
        WHERE d.numero_serie = $6
        ON CONFLICT (chave) DO NOTHING
    """,
        chave,
        regra,
        parametro,
        valor,
        f"Alarme {regra}: valor de {valor}",
        dispositivo
    )
    if resultado not in ("INSERT 0 1", "INSERT 0 0"):
        raise RuntimeError(f"Resultado inesperado: {resultado}")

    if resultado == "INSERT 0 0":
        existe = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM vigilancia_dispositivo WHERE numero_serie = $1)",
            dispositivo
        )

        if not existe:
            raise ValueError(f"Dispositivo desconhecido: {dispositivo}")


async def process_message(message: aio_pika.IncomingMessage, pool, ack_automatico, morrer_antes_do_ack, regras):
    agora = time.time()
    
    try:
        corpo = json.loads(message.body.decode())

        if not isinstance(corpo, dict):
            raise ValueError("A mensagem deve ser um objeto JSON")

    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        print(f"Mensagem JSON inválida: {e}", flush=True)

        if not ack_automatico:
            await message.reject(requeue=False)

        return

    # Extrair os dados da leitura recebida
    dispositivo = corpo.get("dispositivo")
    parametro = corpo.get("parametro")
    valor = corpo.get("valor")

# Identificar todas as regras cuja condição foi satisfeita
    regras_ativas = detetar_alarme(parametro, valor, regras)

    for nome_regra in regras_ativas:
        duracao = regras[nome_regra]["duracao"]

        if duracao == 0:
            print(
            f"ALARME IMEDIATO: {nome_regra} | "
            f"Dispositivo: {dispositivo} | Valor: {valor}",
            flush=True
            )
        else:
            print(
            f"CONDIÇÃO DETETADA: {nome_regra} | "
            f"Duração necessária: {duracao}s | "
            f"Dispositivo: {dispositivo}",
            flush=True
            )
    
    publicado_em = corpo.get("_publicado_em")
    latencia_ms = 0.0

    if publicado_em:
        try:
            data_publicacao = datetime.fromisoformat(publicado_em)
            latencia_ms = (
            agora - data_publicacao.timestamp()
            ) * 1000
        except (ValueError, TypeError):
            print("Aviso: data de publicação inválida", flush=True)


    try:
        instante = datetime.fromisoformat(corpo["instante"])
        valor = float(valor)

        if not math.isfinite(valor):
            raise ValueError("Valor da leitura inválido")

        regras_parametro = obter_regras_parametro(parametro, regras)

        if not regras_parametro:
            if not ack_automatico:
                await message.ack()
            return
        
        async with pool.acquire() as conn:
            async with conn.transaction():

                await conn.execute("""
                    SELECT pg_advisory_xact_lock(
                        hashtextextended($1, 0)
                    )
                """, dispositivo)

                for nome_regra, configuracao in regras_parametro.items():

                    inicio_episodio = await processar_regra(
                        conn,
                        dispositivo,
                        parametro,
                        valor,
                        instante,
                        nome_regra,
                        configuracao
                    )

                    if inicio_episodio is not None:
                        await guardar_alarme(
                            conn,
                            dispositivo,
                            parametro,
                            valor,
                            nome_regra,
                            inicio_episodio
                        )

        # Estas linhas continuam dentro do try
        if morrer_antes_do_ack == 1:
            sys.exit(1)

        if not ack_automatico:
            await message.ack()

        print(json.dumps({
            "evento": "processado",
            "ts": agora,
            "fila": "alarms",
            "latencia_ms": latencia_ms,
            "id": message.message_id
        }), flush=True)

    except (
    asyncpg.PostgresConnectionError,
    asyncpg.DeadlockDetectedError,
    asyncpg.SerializationError,
    OSError
        ) as e:
        print(f"ERRO TEMPORARIO NA BD: {e}", flush=True)

        if not ack_automatico:
            await asyncio.sleep(2)
            await message.nack(requeue=True)

    except Exception as e:
        print(f"ERRO AO PROCESSAR: {e}", flush=True)

        if not ack_automatico:
            await message.reject(requeue=False)

async def main():
    regras = carregar_regras()
    print(f"Regras de alarmes carregadas: {list(regras.keys())}", flush=True)
    amqp_url = os.environ.get("AMQP_URL", "amqp://sivit:devpass@broker:5672/")
    db_url = os.environ.get("DATABASE_URL", "postgresql://sivit:devpass@sivitDB:5432/sivit")
    prefetch = int(os.environ.get("PREFETCH", 10))
    ack_automatico = int(os.environ.get("ACK_AUTOMATICO", 0))
    morrer_apos = int(os.environ.get("MORRER_APOS", 0))
    morrer_antes_do_ack = int(os.environ.get("MORRER_ANTES_DO_ACK", 0))
    max_mensagens = int(os.environ.get("MAX_MENSAGENS", 100000))
    politica_cheia = os.environ.get("POLITICA_CHEIA", "reject-publish")

    while True:
        try:
            pool = await asyncpg.create_pool(db_url)
            print("Ligação ao PostgreSQL estabelecida", flush=True)
            break

        except (asyncpg.PostgresConnectionError, OSError) as e:
            print(
                f"PostgreSQL indisponível: {e}. "
                "Nova tentativa em 5 segundos...",
                flush=True
            )
            await asyncio.sleep(5)
    connection = await aio_pika.connect_robust(amqp_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=prefetch)

    exchange = await channel.declare_exchange("leituras", aio_pika.ExchangeType.TOPIC, durable=True)
    dlx = await channel.declare_exchange("leituras.dlx", aio_pika.ExchangeType.DIRECT, durable=True)

    dlq = await channel.declare_queue("alarms.dlq", durable=True)
    await dlq.bind(dlx, routing_key="alarms")

    args = {
        "x-dead-letter-exchange": "leituras.dlx",
        "x-dead-letter-routing-key": "alarms",
        "x-max-length": max_mensagens,
        "x-overflow": politica_cheia
    }
    queue = await channel.declare_queue("alarms", durable=True, arguments=args)
    await queue.bind(exchange, routing_key="leitura.#")

    count = 0
    async with queue.iterator(no_ack=bool(ack_automatico)) as queue_iter:
        async for message in queue_iter:
            await process_message(message, pool, ack_automatico, morrer_antes_do_ack, regras)
            count += 1
            if morrer_apos > 0 and count >= morrer_apos:
                sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())