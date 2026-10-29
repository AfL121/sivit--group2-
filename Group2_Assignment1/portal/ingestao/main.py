import asyncio
import hmac
import json
import logging
import os
import random
import time
from datetime import datetime, timezone

import aio_pika
import asyncpg
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("ingestao")

# ------------------------------------------------------------------ configuração (RNF3)
PORTAL_URL = os.environ.get("PORTAL_URL", "http://portal:8000")
PORTAL_TOKEN = os.environ.get("PORTAL_TOKEN", "")
GATEWAY_TOKENS = {t.strip() for t in os.environ.get("GATEWAY_TOKENS", "").split(",") if t.strip()}
POR_FILA = int(os.environ.get("POR_FILA", 1))

# Níveis cumulativos, na ordem da tabela do TP4:
# off < sincrona < timeout < retry < disjuntor < cache
MODOS = ["off", "sincrona", "timeout", "retry", "disjuntor", "cache"]
MODO = os.environ.get("MODO_VALIDACAO", "cache")
if MODO not in MODOS:
    raise RuntimeError(f"MODO_VALIDACAO inválido: {MODO} (usar {MODOS})")
NIVEL = MODOS.index(MODO)

TIMEOUT_S = float(os.environ.get("PORTAL_TIMEOUT_S", "0.5"))
CB_FALHAS = int(os.environ.get("CB_FALHAS", "5"))      # falhas seguidas para abrir
CB_PAUSA_S = float(os.environ.get("CB_PAUSA_S", "10"))  # tempo de circuito aberto
CACHE_TTL_S = float(os.environ.get("CACHE_TTL_S", "60"))

# Cópia dos limites do portal (services.LIMITES_PLAUSIVEIS): a ingestão é outro
# serviço e não pode importar código Django. Manter os dois sincronizados.
LIMITES = {
    "FC": (20, 250), "SPO2": (50, 100), "TEMP": (30, 45),
    "PAS": (40, 260), "PAD": (20, 160), "FR": (4, 60),
}


class Reading(BaseModel):
    dispositivo: str
    instante: datetime
    parametro: str
    valor: float
    unidade: str


# ------------------------------------------------------------------ estado
pool = None
broker_conn = None
exchange = None
cliente_portal = None

_falhas = 0
_aberto_ate = 0.0
_cache: dict[str, float] = {}


async def iniciar():
    """Corre uma vez quando o serviço arranca: abre as ligações."""
    global pool, broker_conn, exchange, cliente_portal
    if not GATEWAY_TOKENS:
        log.warning("GATEWAY_TOKENS vazio: todos os pedidos serão recusados (401)")
    log.info("modo de validação: %s", MODO)

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    broker_conn = await aio_pika.connect_robust(os.environ["AMQP_URL"])
    usa_confirms = bool(int(os.environ.get("CONFIRMS", 1)))
    channel = await broker_conn.channel(publisher_confirms=usa_confirms)
    exchange = await channel.declare_exchange("leituras", aio_pika.ExchangeType.TOPIC, durable=True)

    cliente_portal = httpx.AsyncClient(
        base_url=PORTAL_URL,
        headers={"Authorization": f"Token {PORTAL_TOKEN}"},
        # nível "sincrona" = SEM timeout, para reproduzir a falha em cascata
        timeout=None if NIVEL == 1 else TIMEOUT_S,
    )

async def terminar():
    """Corre uma vez quando o serviço para: fecha as ligações."""
    await cliente_portal.aclose()
    await pool.close()
    await broker_conn.close()


app = FastAPI()
app.add_event_handler("startup", iniciar)
app.add_event_handler("shutdown", terminar)


# ------------------------------------------------------------------ autenticação do gateway (RF2)
def autenticar(authorization: str | None = Header(default=None)):
    esquema, _, token = (authorization or "").partition(" ")
    ok = esquema.lower() == "token" and any(
        hmac.compare_digest(token.encode(), t.encode()) for t in GATEWAY_TOKENS)
    if not ok:
        raise HTTPException(401, "token de gateway inválido ou em falta",
                            headers={"WWW-Authenticate": "Token"})


# ------------------------------------------------------------------ validação do dispositivo (TP4-E3)
async def _consultar_portal(serial: str) -> bool:
    """Uma tentativa. True/False = resposta definitiva; exceção = portal indisponível."""
    r = await cliente_portal.get(f"/api/v1/devices/{serial}/")
    if r.status_code == 404:
        return False
    r.raise_for_status()
    return r.json().get("admission") is not None


def _registar_falha():
    global _falhas, _aberto_ate
    _falhas += 1
    if NIVEL >= 4 and _falhas >= CB_FALHAS:
        _aberto_ate = time.monotonic() + CB_PAUSA_S   # após a pausa, a 1.ª falha reabre


async def estado_dispositivo(serial: str):
    """True = válido, False = inválido, None = não foi possível verificar."""
    global _falhas
    if NIVEL == 0:
        return True
    agora = time.monotonic()
    if NIVEL >= 5 and _cache.get(serial, 0) > agora:
        return True
    if NIVEL >= 4 and agora < _aberto_ate:
        return None                                   # circuito aberto: nem tenta

    tentativas = 3 if NIVEL >= 3 else 1
    for i in range(tentativas):
        try:
            valido = await _consultar_portal(serial)
        except Exception as e:                        # noqa: BLE001
            log.warning("portal indisponível (%s): %s", type(e).__name__, e)
            _registar_falha()
            if i + 1 < tentativas:
                # backoff exponencial com jitter total: evita a "thundering herd"
                await asyncio.sleep(random.uniform(0, 0.1 * 2 ** i))
        else:
            _falhas = 0
            if valido and NIVEL >= 5:
                _cache[serial] = time.monotonic() + CACHE_TTL_S
            return valido
    return None   # fail open: perder uma leitura clínica é pior do que aceitá-la sem validar


def plausivel(r: Reading):
    limites = LIMITES.get(r.parametro)
    if limites is None:
        return "parametro_desconhecido"
    if not limites[0] <= r.valor <= limites[1]:     # também rejeita NaN
        return "valor_implausivel"
    return None


# ------------------------------------------------------------------ publicação
async def publish(r: Reading, nao_validado: bool = False):
    body = r.model_dump(mode="json")
    body["_publicado_em"] = datetime.now(timezone.utc).isoformat()
    if nao_validado:
        body["_nao_validado"] = True                  # para reconciliação posterior
    mensagem = aio_pika.Message(
        body=json.dumps(body).encode(),
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        message_id=f"{r.dispositivo}|{r.instante.isoformat()}|{r.parametro}",
    )
    await exchange.publish(mensagem, routing_key=f"leitura.{r.parametro.lower()}.{r.dispositivo}")


async def ingest(batch: list[Reading]):
    if not batch:
        return {"received": 0, "accepted": 0, "rejected": 0}

    # uma verificação por dispositivo DISTINTO, em paralelo
    series = list({r.dispositivo for r in batch})
    estados = dict(zip(series, await asyncio.gather(*(estado_dispositivo(s) for s in series))))

    aceites, rejeitadas = [], []
    for r in batch:
        motivo = plausivel(r)
        if motivo is None and estados[r.dispositivo] is False:
            motivo = "dispositivo_sem_internamento"
        if motivo:
            rejeitadas.append({"dispositivo": r.dispositivo,
                               "instante": r.instante.isoformat(), "motivo": motivo})
        else:
            aceites.append((r, estados[r.dispositivo] is None))

    if rejeitadas:
        log.warning("%d leituras rejeitadas num lote de %d", len(rejeitadas), len(batch))
    if not aceites:
        raise HTTPException(422, detail={"rejected": rejeitadas[:20]})

    if POR_FILA == 0:
        rows = [(r.dispositivo, r.instante, r.parametro, r.valor, r.unidade) for r, _ in aceites]
        async with pool.acquire() as c:
            await c.executemany("""
                INSERT INTO vigilancia_leitura (dispositivo_id, instante, parametro, valor, unidade)
                VALUES ((SELECT id FROM vigilancia_dispositivo WHERE numero_serie = $1), $2, $3, $4, $5)
                ON CONFLICT (dispositivo_id, instante, parametro) DO NOTHING
            """, rows)
    else:
        try:
            await asyncio.gather(*(publish(r, nv) for r, nv in aceites))
        except Exception:
            raise HTTPException(503, detail="broker indisponivel")

    return {"received": len(batch), "accepted": len(aceites),
            "rejected": len(rejeitadas), "rejected_detail": rejeitadas[:20]}


# ------------------------------------------------------------------ saúde (RF2)
# vivo: o processo responde. Não depende de nada: se falhar, reinicia-se.
def live():
    return {"estado": "vivo"}


# pronto: consegue cumprir a sua função (broker, ou BD no modo direto).
# NÃO inclui o portal: senão um portal lento tirava a ingestão de serviço (cascata).
async def ready(response: Response):
    try:
        if POR_FILA == 0:
            async with pool.acquire() as c:
                await c.execute("SELECT 1")
        elif broker_conn is None or broker_conn.is_closed:
            raise RuntimeError("broker fechado")
        return {"estado": "pronto"}
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"estado": "indisponivel"}


# Cada linha liga uma morada (URL) a uma função.
app.add_api_route("/v1/leituras", ingest, methods=["POST"], status_code=202,
                  dependencies=[Depends(autenticar)])
app.add_api_route("/saude/vivo", live, methods=["GET"])
app.add_api_route("/health/live", live, methods=["GET"])
app.add_api_route("/saude/pronto", ready, methods=["GET"])
app.add_api_route("/health/ready", ready, methods=["GET"])
