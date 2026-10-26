# Relatório TP2: Multitiered Application in Django

----------------------------------------------------------------

## Exercício 1: The constraint that is not decoration
* **Modelo `Reading` e Restrições:** A definição do modelo inclui uma restrição de unicidade composta sobre `[device, instant, parameter]` e um índice focado na obtenção rápida da última leitura[cite: 25].
* **Idempotência na Ingressão (B7):** Esta restrição `UNIQUE` na base de dados garante que se um gateway retransmitir o mesmo lote de leituras (por falta de confirmação anterior), a base de dados rejeita duplicados de forma atómica, tornando a operação segura face a reentregas[cite: 25].

----------------------------------------------------------------

## Exercício 2: Splitting off the Data Tier

### 1. Que tipo de falha é esta (na taxonomia B7)?
Trata-se de uma **falha de conectividade transiente da camada de dados** (ou *temporary network partition / service crash*). A camada de processamento perde a capacidade de comunicar com a camada de dados persistente.

### 2. O utilizador vê um erro compreensível ou um stack trace?
Se a variável `DEBUG` estiver a `0` (modo produção), o utilizador vê uma **página de erro genérica (500 Internal Server Error)** tratada pelo Nginx/Gunicorn. Se `DEBUG=1`, expõe o *stack trace* (com detalhes de SQL e definições), o que representa uma vulnerabilidade em produção.

### 3. O portal recupera por si próprio quando a BD regressa? Quanto tempo demora?
**Sim, recupera automaticamente.** Como o Django estabelece ligações à base de dados por pedido (*per-request connections*), assim que o contentor `sivitDB` fica saudável e pronto a responder a `pg_isready`, o pedido seguinte estabelece com sucesso a ligação sem necessitar de reiniciar o portal.

----------------------------------------------------------------

## Exercício 3: The Production Stack

### 1. Identificar as três camadas de B2 neste stack. Quais partilham contentor e porquê?
* **Apresentação:** Nginx (serve ficheiros estáticos e atua como *reverse proxy*).
* **Processamento:** Gunicorn + Django (executa a lógica de negócio e renderização dinâmicamente).
* **Dados:** PostgreSQL (`sivitDB`).
* **Partilha de contentor:** Nginx e Gunicorn/Django estão em contentores separados para manter a separação de responsabilidades (B2), permitindo escalar o processamento de forma independente sem duplicar a gestão de ficheiros estáticos.

### 2. `--workers 3`: qual o modelo de concorrência de B3? Quantos pedidos simultâneos processa?
Utiliza o **modelo de concorrência por múltiplos processos síncronos (Pre-fork Worker Model)**. Trata até **3 pedidos estritamente simultâneos** (um por cada processo *worker*). Pedidos adicionais ficam em fila de espera ao nível da tomada TCP (*socket backlog*) do Nginx/Gunicorn até um *worker* ficar livre.

### 3. Por que razão os ficheiros estáticos são servidos pelo Nginx e não pelo Django?
O Nginx é altamente otimizado para operações de E/S de ficheiros (usando `sendfile` diretamente ao nível do kernel do Linux), libertando os *workers* do Gunicorn/Django (que consomem muita memória e tempo de CPU) para processarem exclusivamente lógica dinâmica em Python.

### 4. `proxy_read_timeout 10s`: o que acontece sem esta linha se o Django bloquear?
Sem esse limite de tempo, se uma consulta no Django bloquear ou entrar num ciclo infinito, a ligação do cliente HTTP/Nginx permanece aberta indefinidamente (*connection leak*), esgotando os *workers* do Nginx e provocando uma **falha em cascata (Cascading Failure)** que impede novos utilizadores de aceder ao sistema.

----------------------------------------------------------------

## Exercício 4: O Efeito N+1 (Medição Real no SIVIT)

| Versão | Número de Queries |
| :--- | :---: |
| Naive (Ingénuo) | 101 |
| + select_related | 81 |
| + prefetch_related | 62 |
| + subquery for last reading | 2 |

