# Comandi rapidi. Serve uv (https://docs.astral.sh/uv/).
# I file GME non si scaricano mai in automatico: se li vuoi, mettili a mano in data/gme/.
# La descrizione dopo "##" su ogni comando è quella mostrata da `make help`.

.PHONY: help run public backtest test

help: ## questo aiuto (anche solo `make`)
	@uv run --no-project python -I -c "import re; print('Previsione PUN - comandi'); [print(f'  make {t:<10} {d}') for t, d in re.findall(r'^([a-z]+):.*?## (.*)$$', open('Makefile', encoding='utf-8').read(), re.M)]; print('File GME facoltativi: scaricali a mano in data/gme/ prima di make run.')"

run: ## pagina locale: scarica i dati in parallelo, lancia Timestral, rigenera data/out/index.html
	uv run --extra local pun build --profile local

public: ## pagina pubblica, solo zona Nord: site/index.html
	uv run pun build --profile public

backtest: ## backtest completo del flusso locale (circa un'ora di CPU)
	uv run --extra local pun backtest --profile local

test: ## test offline
	uv run --group dev pytest -q
