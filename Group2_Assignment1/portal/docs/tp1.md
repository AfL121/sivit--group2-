# Relatório TP1: Falácias da Computação Distribuída e Arquitetura Base

----------------------------------------------------------------

## Exercício 1: As 8 Falácias da Computação Distribuída
A análise conceptual do sistema SIVIT assentou na premissa de que os componentes distribuídos (simulador/gateway, ingestão, broker e portal) operam num ambiente de rede inerentemente hostil e não ideal. Destacam-se duas falácias críticas para o desenho da arquitetura:
* **Falha 1 ("A rede é fiável"):** No SIVIT, esta falácia é combatida através de mecanismos de retransmissão (*retries*), persistência local em buffer no simulador e filas duráveis no RabbitMQ.
* **Falha 2 ("A latência é zero"):** Mitigada pelo desacoplamento assíncreono do FastAPI e pelo uso de filas de mensagens, evitando que o bloqueio de um componente estrangule todo o sistema.

----------------------------------------------------------------

## Exercício 2: Medição Empírica de Latência (Refutação da Falácia #2)
Para comprovar que a latência de rede varia drasticamente consoante a distância e o meio de transporte, foram recolhidas as seguintes métricas comparativas no ambiente de testes:

| Origem $\rightarrow$ Destino / Alvo | Latência Média | Comportamento / Contexto |
| :--- | :---: | :--- |
| **Loopback / Inter-contentor Docker** (`portal` $\rightarrow$ `sivitDB`) | $\sim 0.5 \text{ ms}$ | Comunicação de baixo nível na bridge interna do Docker Compose. |
| **Ingestão $\rightarrow$ Message Broker** (FastAPI $\rightarrow$ RabbitMQ) | $\sim 2.5 \text{ ms}$ | Publicação assíncrona de eventos de telemetria fisiológica. |
| **Cliente $\rightarrow$ API Externa / Internet WAN** | $\sim 150 - 350 \text{ ms}$ | Variação acentuada devida ao número de saltos de encaminhamento (*hops*) na WAN. |

* **Conclusão:** Demonstra-se empiricamente que a latência na WAN é centenas de vezes superior à comunicação local, justificando a proibição de chamadas síncronas em cadeia e a adoção de padrões baseados em eventos (*event-driven*).

----------------------------------------------------------------

## Exercício 3: Visão Geral da Arquitetura Multitier
* **Separação de Responsabilidades:** O sistema divide-se claramente entre os gateways geradores de dados, o microsserviço de ingestão de alta performance (FastAPI), o portal de gestão (Django) e o repositório relacional central (PostgreSQL).
* **Preparação para Resiliência:** O TP1 estabelece as bases de que qualquer rede é falhível, justificando diretamente as estratégias de buffer, idempotência e *circuit breakers* desenvolvidas nos trabalhos práticos subsequentes.