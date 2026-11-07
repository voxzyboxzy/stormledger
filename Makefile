.PHONY: start build test refresh serve

start:
	./scripts/start.sh

build:
	python -m stormledger.cli build

refresh:
	python -m stormledger.cli refresh

serve:
	python -m stormledger.cli serve

test:
	pytest -q
	cd frontend && npm test
