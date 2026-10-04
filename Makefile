.PHONY: dev dev-stop

dev:
	@bash scripts/dev.sh

dev-stop:
	docker compose -p stride-dev -f compose.dev.yaml stop
