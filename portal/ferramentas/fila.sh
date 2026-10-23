#!/usr/bin/env bash
# Utilitários de inspeção do broker, usados pelos scripts dos exercícios.
#
#   ./ferramentas/fila.sh profundidade [fila]
#   ./ferramentas/fila.sh tabela
#   ./ferramentas/fila.sh purgar
set -euo pipefail
cd "$(dirname "$0")/.."

rabbit() { docker compose exec -T broker rabbitmqctl "$@" 2>/dev/null; }

case "${1:-tabela}" in
  profundidade)
    rabbit list_queues name messages --quiet --no-table-headers \
      | awk -v f="${2:-arquivo}" '$1==f {print $2}'
    ;;
  tabela)
    printf '%-22s %10s %10s %12s\n' FILA MENSAGENS PRONTAS CONSUMIDORES
    rabbit list_queues name messages messages_ready consumers --quiet --no-table-headers \
      | awk '{printf "%-22s %10s %10s %12s\n", $1, $2, $3, $4}'
    ;;
  purgar)
    for f in arquivo alarmes painel estatisticas arquivo.dlq alarmes.dlq painel.dlq estatisticas.dlq; do
      rabbit purge_queue "$f" >/dev/null 2>&1 || true
    done
    echo "filas purgadas"
    ;;
  *) echo "uso: $0 {profundidade [fila]|tabela|purgar}" >&2; exit 2 ;;
esac
