# Relatório TP5: Testes de Carga, Resiliência e Tolerância a Falhas

----------------------------------------------------------------

## 1. Introdução e Enquadramento
O TP5 foca-se na validação empírica do comportamento do sistema sob stress, avaliando a robustez do pipeline assíncrono (FastAPI $\rightarrow$ RabbitMQ $\rightarrow$ Workers) e os mecanismos de resiliência e recuperação automática perante falhas de rede e indisponibilidade de serviços a jusante.

----------------------------------------------------------------

## 2. Teste de Carga e Desempenho do RabbitMQ
Através de testes de carga executados sobre o microsserviço de ingestão, validou-se a capacidade do broker de mensagens em processar lotes de leituras fisiológicas sem perda de dados:

* **Métricas Globais de Ingestão:**
  * Pedidos HTTP aceites (código `202 Accepted`): **92 / 92** (Taxa de sucesso de 100%).
  * Erros HTTP e falhas lógicas: **0**.
  * Leituras totais enviadas e confirmadas: **920**.
  * Leituras perdidas: **0**.
* **Latências Registadas:**
  * Média: `543.75 ms`
  * Percentil 50 ($p_{50}$): `516.61 ms`
  * Percentil 95 ($p_{95}$): `915.26 ms`
  * Percentil 99 ($p_{99}$): `1163.56 ms`
* **Estado das Filas do RabbitMQ (pós-consumo pelos Workers):**
  * Filas principais (`display`, `alarms`, `arquivo`): **0 mensagens pendentes** (consumidas na totalidade pelos respetivos *workers*).
  * *Dead Letter Queues* (`.dlq`): **0 mensagens** (sem registo de rejeições ou anomalias estruturais nos payloads).

----------------------------------------------------------------

## 3. Resiliência, Buffer Local e Recuperação Automática (*Replay*)
Para testar a robustez do simulador e do cliente face a interrupções na camada de ingestão, foi simulada uma falha prolongada do serviço:

* **Comportamento sob Falha (`ConnectError`):** 
  * O simulador detetou a indisponibilidade da ingestão (`[ERRO] Ingestão indisponível`).
  * Para evitar a perda de dados em memória, o sistema ativou o **buffer local em disco**, acumulando de forma segura os lotes não enviados (`[BUFFER] Lote guardado em disco`).
* **Recuperação e Replay Automático:**
  * Assim que o microsserviço de ingestão foi restabelecido, o simulador iniciou o processo de *replay* automático (`[REPLAY] Lote antigo enviado`), esvaziando o buffer local de forma cadenciada até atingir 0 pendentes.
* **Conclusão de Resiliência:** O mecanismo garante **0% de perda de dados** mesmo em cenários de partição de rede temporária ou falha sistémica da ingestão.

----------------------------------------------------------------

## 4. Persistência e Volume de Dados na Base de Dados
A validação da persistência em larga escala na base de dados relacional (PostgreSQL) demonstrou um acumulado estável e contínuo de **56 028 registos** persistidos, atestando a fiabilidade a longo prazo de todo o ecossistema SIVIT para o checkpoint da Semana 6.