import argparse
import asyncio
import json
import os
import random
import time
from datetime import datetime, timezone
import httpx

# Tudo o que muda entre máquinas vem do ambiente (RNF3). Dentro do compose:
#   BUFFER_FILE=/dados/buffer_leituras.json   (num volume, para sobreviver a reinícios)
BUFFER_FILE = os.environ.get("BUFFER_FILE", "buffer_leituras.json")
URL_POR_OMISSAO = os.environ.get("INGESTAO_URL", "http://localhost:8001/v1/leituras")
TOKEN = os.environ.get("INGESTAO_TOKEN", "")


def gerar_leitura(n_dispositivos):
    # Gera sinais vitais realistas exigidos pelo guião
    dispositivo = f"SN-{random.randint(1, n_dispositivos):04d}-{random.randint(0, 2)}"
    instante = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    # Parâmetro clínico com alguma variabilidade
    parametro = random.choice(["FC", "SPO2", "TEMP"])
    if parametro == "FC":
        valor = round(random.uniform(60, 100), 1)
        unidade = "bpm"
    elif parametro == "SPO2":
        # Simula ocasionalmente oclusões/quedas abruptas
        valor = round(random.uniform(85, 100), 1) if random.random() > 0.1 else round(random.uniform(70, 80), 1)
        unidade = "%"
    else:
        # Temperatura com ligeiro drift
        valor = round(random.uniform(36.0, 38.5), 1)
        unidade = "ºC"

    return {
        "dispositivo": dispositivo,
        "instante": instante,
        "parametro": parametro,
        "valor": valor,
        "unidade": unidade,
    }

def carregar_buffer():
    if os.path.exists(BUFFER_FILE):
        try:
            with open(BUFFER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def guardar_buffer(buffer):
    # Escreve num ficheiro temporário e só depois substitui: se o processo
    # morrer a meio da escrita, o buffer antigo fica intacto em vez de
    # ficar meio escrito (e perderem-se todas as leituras guardadas).
    pasta = os.path.dirname(BUFFER_FILE)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    tmp = BUFFER_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(buffer, f)
    os.replace(tmp, BUFFER_FILE)


def deve_guardar(codigo):
    """Que resposta HTTP justifica guardar o lote para reenviar mais tarde?

    5xx, 408 e 429 são problemas temporários do serviço: reenviar depois pode
    resultar. Os outros 4xx (400, 401, 422...) dizem que o LOTE está errado:
    reenviá-lo para sempre bloquearia todos os lotes seguintes (a fila de
    reenvio é processada por ordem), por isso descarta-se e regista-se.
    """
    return codigo >= 500 or codigo in (408, 429)


async def enviar(cliente, url, lote):
    """Tenta enviar um lote. Devolve 'ok', 'guardar' ou 'descartar'."""
    try:
        r = await cliente.post(url, json=lote)
    except Exception as e:                       # rede em baixo, timeout, etc.
        print(f"[ERRO] Ingestão indisponível ({type(e).__name__}).")
        return "guardar"
    if r.status_code < 400:
        return "ok"
    if deve_guardar(r.status_code):
        print(f"[AVISO] Ingestão respondeu {r.status_code} (temporário).")
        return "guardar"
    print(f"[DESCARTADO] Ingestão rejeitou o lote com {r.status_code}: {r.text[:200]}")
    return "descartar"


async def main(args):
    print(f"[*] Simulador a iniciar. Destino: {args.url} | Dispositivos: {args.dispositivos}")
    buffer = carregar_buffer()
    if buffer:
        print(f"[*] Encontrados {len(buffer)} lotes em buffer local por enviar.")

    ciclo = 0
    async with httpx.AsyncClient(timeout=5.0, headers={"Authorization": f"Token {TOKEN}"}) as cliente:
        while args.ciclos == 0 or ciclo < args.ciclos:
            ciclo += 1
            lote = [gerar_leitura(args.dispositivos) for _ in range(args.lote)]
            servico_ok = True

            # 1. Replay: reenvia UM lote antigo por ciclo, por ordem.
            if buffer:
                resultado = await enviar(cliente, args.url, buffer[0])
                if resultado == "ok":
                    buffer.pop(0)
                    guardar_buffer(buffer)
                    print(f"[REPLAY] Lote antigo enviado. Restam {len(buffer)} no buffer.")
                elif resultado == "descartar":
                    buffer.pop(0)
                    guardar_buffer(buffer)
                else:
                    servico_ok = False

            # 2. Lote atual: só se tentou o replay sem o serviço falhar.
            if servico_ok:
                resultado = await enviar(cliente, args.url, lote)
                if resultado == "ok":
                    print(f"[OK] Lote de {args.lote} leituras enviado.")
                elif resultado == "guardar":
                    buffer.append(lote)
                    guardar_buffer(buffer)
                    print(f"[BUFFER] Lote guardado em disco. {len(buffer)} por enviar.")
            else:
                buffer.append(lote)
                guardar_buffer(buffer)
                print(f"[BUFFER] Serviço ainda em baixo. {len(buffer)} por enviar.")

            await asyncio.sleep(args.intervalo)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url", default=URL_POR_OMISSAO, nargs="?")
    p.add_argument("--dispositivos", type=int, default=20)
    p.add_argument("--lote", type=int, default=10)
    p.add_argument("--intervalo", type=float, default=1.0, help="Intervalo em segundos entre envios")
    p.add_argument("--ciclos", type=int, default=0, help="Parar após N envios (0 = infinito)")
    asyncio.run(main(p.parse_args()))
