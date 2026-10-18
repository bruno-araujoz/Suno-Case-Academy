#!/usr/bin/env bash
# Prepara o projeto do zero (clone limpo → banco populado → testes verdes).
#   bash scripts/bootstrap.sh            # completo
#   bash scripts/bootstrap.sh --quick    # pula o histórico do Copom (só coleta recente)
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "Falta '$1' no PATH: $2" >&2; exit 1; }; }

need uv "instale com: curl -LsSf https://astral.sh/uv/install.sh | sh"
need docker "instale o Docker (Desktop ou Engine) e deixe-o rodando"

step "Dependências Python (uv sync)"
uv sync

if [ ! -f .env ]; then
  step "Criando .env a partir de .env.example (preencha as chaves de LLM para gerar conteúdo)"
  cp .env.example .env
fi

step "PostgreSQL (docker compose up -d db)"
docker compose up -d db
for _ in $(seq 1 60); do
  docker compose exec -T db pg_isready -U postgres -d suno_content >/dev/null 2>&1 && break
  sleep 1
done
docker compose exec -T db pg_isready -U postgres -d suno_content

if [ "${1:-}" != "--quick" ]; then
  step "Histórico de atas/comunicados do Copom desde 2016 (glossário e calibração) — ~2 min"
  uv run python scrape.py backfill --source bcb_copom --year 2016 --no-enrich
fi

step "Coleta inicial de todas as fontes (migrations incluídas) — ~1–3 min"
uv run python scrape.py refresh --budget 300

step "Testes offline"
uv run pytest -q

cat <<'MSG'

Pronto. Próximos passos:
  uv run uvicorn web.app:app --port 8000                          # UI em http://localhost:8000
  uv run python generate.py --format carrossel --level iniciante   # CLI
  uv run python evaluate.py batch --events 3                       # lote + matriz de confusão
Para gerar conteúdo, preencha ao menos uma chave de LLM no .env (GROQ_API_KEY, GEMINI_API_KEY...).
MSG
