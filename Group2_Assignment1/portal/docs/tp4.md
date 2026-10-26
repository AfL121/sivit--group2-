# Relatório TP4: O Microsserviço de Ingestão (FastAPI)

----------------------------------------------------------------

## Exercício 1: Arquitetura Assíncrona e o Event Loop
* **Modelo Concorrente:** O FastAPI utiliza Uvicorn baseado em `asyncio` (Event Loop assíncrono), permitindo gerir milhares de conexões concorrentes de I/O de forma eficiente sem bloquear threads principais para cada pedido de rede.
* **Desacoplamento:** O microsserviço valida os dados recebidos dos gateways e publica-os de forma assíncrona no message broker (RabbitMQ), isolando o portal de picos repentinos de tráfego fisiológico.

----------------------------------------------------------------

## Exercício 2: Avaliação de Concorrência (Async vs Blocking)
Abaixo encontram-se os resultados da avaliação de desempenho comparativa entre endpoints síncronos e assíncronos no microsserviço de ingestão:

| Endpoint | Throughput (req/s) | p50 (ms) | p99 (ms) | Comentário / Comportamento |
| :--- | :---: | :---: | :---: | :--- |
| **`/test/blocking`** | ~5 | 200 | 250 | Saturação imediata das threads disponíveis devido a operações de bloqueio síncrono. |
| **`/test/async`** | ~250 | 201 | 210 | Elevado débito mantido através do uso eficiente de coroutinas e operações não bloqueantes. |
| **`/test/thread`** | ~200 | 202 | 220 | Desempenho aceitável via pool de threads, embora com maior sobrecarga de contexto (*context switching*). |

----------------------------------------------------------------

## Exercício 3: Falha em Cascata e Mecanismos de Resiliência
Quando a camada de processamento/portal sofre degradação ou latência extrema, o microsserviço de ingestão emprega padrões defensivos para evitar o esgotamento de recursos em cascata:

| Configuração de Resiliência | Throughput (req/s) | Leituras Perdidas | p99 (ms) | Observações Arquiteturais |
| :--- | :---: | :---: | :---: | :--- |
| **Synchronous, portal healthy** | 150 | 0 | 45 | Estado nominal de funcionamento sem perturbações na rede. |
| **Synchronous, portal at 3s delay** | 2 | 450 | 3200 | **Falha em Cascata:** Esgotamento total de conexões e latência catastrófica. |
| **+ Timeout (500 ms)** | 45 | 120 | 510 | Corta conexões lentas libertando recursos, mas gera perda de dados se não houver retentativa. |
| **+ Retry com Backoff e Jitter** | 60 | 30 | 650 | Suaviza novas tentativas distribuindo o tráfego no tempo (*jitter* evita tempestades de retransmissão). |
| **+ Circuit Breaker** | 180 | 0 | 12 | **Proteção Ativa:** Deteta a falha a jusante e rejeita pedidos rapidamente sem sobrecarregar o portal. |
| **+ Local Cache (60s)** | 350 | 0 | 8 | Resposta imediata baseada em cache local em memória durante falhas sistémicas transientes. |