import argparse
import asyncio
import json
import os
import random
import time
from datetime import datetime, timezone
import httpx

BUFFER_FILE = "ferramentas/buffer_leituras.json"

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
    with open(BUFFER_FILE, "w") as f:
        json.dump(buffer, f)

async def main(args):
    print(f"[*] Simulador a iniciar. Destino: {args.url} | Dispositivos: {args.dispositivos}")
    buffer = carregar_buffer()
    if buffer:
        print(f"[*] Encontrados {len(buffer)} lotes em buffer local por enviar.")

    async with httpx.AsyncClient(timeout=5.0) as cliente:
        while True:
            # 1. Gerar lote de leituras
            lote = [gerar_leitura(args.dispositivos) for _ in range(args.lote)]
            
            # Tentar enviar primeiro o que está acumulado no buffer (replay)
            enviado_com_sucesso = True
            
            if buffer:
                # Tenta reenviar o primeiro lote do buffer
                lote_antigo = buffer[0]
                try:
                    r = await cliente.post(args.url, json=lote_antigo)
                    if r.status_code < 400:
                        buffer.pop(0)
                        guardar_buffer(buffer)
                        print(f"[REPLAY] Lote recuperado do disco enviado com sucesso. Restam {len(buffer)} no buffer.")
                    else:
                        enviado_com_sucesso = False
                except Exception:
                    enviado_com_sucesso = False

            # 2. Enviar o lote atual se o sistema estiver saudável
            if enviado_com_sucesso:
                try:
                    r = await cliente.post(args.url, json=lote)
                    if r.status_code < 400:
                        print(f"[OK] Lote de {args.lote} leituras enviado com sucesso.")
                    else:
                        print(f"[AVISO] Ingestão rejeitou com código {r.status_code}. A guardar em buffer...")
                        buffer.append(lote)
                        guardar_buffer(buffer)
                except Exception as e:
                    print(f"[ERRO] Ingestão indisponível ({type(e).__name__}). A guardar lote em disco...")
                    buffer.append(lote)
                    guardar_buffer(buffer)
            else:
                # Se o replay falhou, guarda também o lote novo atual
                buffer.append(lote)
                guardar_buffer(buffer)

            await asyncio.sleep(args.intervalo)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url", default="http://localhost:8001/v1/readings", nargs="?")
    p.add_argument("--dispositivos", type=int, default=20)
    p.add_argument("--lote", type=int, default=10)
    p.add_argument("--intervalo", type=float, default=1.0, help="Intervalo em segundos entre envios")
    asyncio.run(main(p.parse_args()))