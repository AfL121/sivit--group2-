# Relatório TP3: REST API com Django REST Framework

----------------------------------------------------------------

## Exercício 1: Design de Recursos e Serializers
* **Estrutura e Versionamento:** A API foi desenhada com versionamento no URI (`/api/v1/`), assegurando a estabilidade dos contratos com os gateways.
* **Serializers:** Utilização de `SlugRelatedField` para identificar dispositivos pelo número de série (evitando expor chaves primárias internas) e validação de parâmetros fisiológicos.

----------------------------------------------------------------

## Exercício 2: Idempotência e Semântica de Falha

### 1. Semântica Implementada
Foi implementada a semântica de **at-least-once** no cliente com **idempotência na camada de dados** (garantindo um comportamento atómico equivalente a *exactly-once* do ponto de vista do estado final).

### 2. Validação Prática da Idempotência (Shell do Django)
Em teste prático realizado sobre a entidade `Leitura`, a tentativa de inserção de um registo duplicado com as mesmas coordenadas `(dispositivo, instante, parametro)` resultou na seguinte exceção de base de dados:

* **Resultado do Teste:** `IntegrityError` lançado pelo PostgreSQL.
* **Conclusão:** A restrição `UNIQUE` impede atomicamente a duplicação de registos durante retransmissões (*retries*) de lotes por parte do microsserviço ou gateway.

### 3. Restrição UNIQUE vs. Chave de Idempotência
* A restrição `UNIQUE` (`dispositivo, instante, parametro`) resolve a duplicação em dados que possuem uma chave natural inerente (sinais vitais).
* Operações sem chave natural (como o reconhecimento de um alarme) exigem uma tabela explícita de `IdempotencyKey` para mapear a chave do pedido à resposta armazenada.

### 4. Gestão da Resposta Fora da Transação
Se a gravação da chave de idempotência ocorrer fora da transação principal, uma falha de rede intermédia pode fazer com que o registo seja criado na BD sem que o cliente receba a confirmação, gerando inconsistência em *retries* subsequentes.

----------------------------------------------------------------

## Exercício 3: O Custo da Paginação (com 50 000 leituras)

| Estratégia de Paginação | Desempenho e Comportamento |
| :--- | :--- |
| **No pagination** | Consumo excessivo de memória no servidor e risco elevado de *timeout* com grandes volumes de dados. |
| **Offset (`?page=`)** | Degradação progressiva da latência em páginas avançadas devido à necessidade de saltar (*OFFSET*) $n$ linhas na BD. |
| **Cursor (`?after=<instant>&limit=100`)** | Desempenho constante e latência previsível, apoiado nos índices compostos da tabela `Leitura`. |

----------------------------------------------------------------

## Exercício 4: Autenticação de Máquinas e OpenAPI
* **Autenticação:** Suporte a tokens individuais por gateway de enfermaria para isolamento de segurança.
* **Esquema OpenAPI:** Documentação interativa servida via `drf-spectacular` em `/api/schema/swagger-ui/`.