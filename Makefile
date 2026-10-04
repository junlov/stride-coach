.PHONY: dev dev-stop

dev:
	@bash scripts/dev.sh

dev-stop:
	@bash scripts/dev-compose.sh stop
