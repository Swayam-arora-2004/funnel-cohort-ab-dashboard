# The only commands a user needs. See docs/TECH_SPECS.md section 8.
.PHONY: help db-up db-wait db-init load views test lint security app export db-down db-nuke psql

SHELL := /bin/bash
include .env
export

# Role names and passwords are passed as psql variables so they never appear in a .sql
# file (SEC-2). ON_ERROR_STOP makes a failed DDL statement fail the whole make target.
PSQL := docker compose exec -T -e PGPASSWORD=$(POSTGRES_PASSWORD) db \
        psql -v ON_ERROR_STOP=1 -U $(POSTGRES_USER) -d $(PG_DB) \
        -v loader_user=$(LOADER_USER) -v loader_password=$(LOADER_PASSWORD) \
        -v ro_user=$(RO_USER) -v ro_password=$(RO_PASSWORD)

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

db-up: ## Start PostgreSQL and wait until it accepts connections
	docker compose up -d
	@$(MAKE) --no-print-directory db-wait

db-wait:
	@echo "waiting for postgres..."
	@for i in $$(seq 1 40); do \
		if docker compose exec -T db pg_isready -U $(POSTGRES_USER) -d $(PG_DB) >/dev/null 2>&1; then \
			echo "postgres ready"; exit 0; fi; sleep 2; done; \
		echo "postgres did not become ready"; exit 1

db-init: ## Create schemas, roles, tables and indexes (idempotent)
	@for f in sql/ddl/*.sql; do echo "-- $$f"; $(PSQL) -f /dev/stdin < $$f; done

load: ## Load the CSVs from data/raw into schema raw
	python -m src.load.load_raw

views: ## Create or replace every analytics view (idempotent)
	@for f in sql/views/*.sql; do echo "-- $$f"; $(PSQL) -f /dev/stdin < $$f; done

test: ## Run the test suite
	pytest

lint: ## ruff lint + format check
	ruff check .
	ruff format --check .

security: ## bandit + pip-audit (SEC-12)
	bandit -q -r src app
	pip-audit -r requirements.txt

app: ## Run the Streamlit dashboard
	streamlit run app/Home.py --logger.level=info

export: ## Export analytics views to exports/*.csv for Tableau Public
	python -m src.export.export_views

psql: ## Open an interactive psql shell as superuser
	docker compose exec -e PGPASSWORD=$(POSTGRES_PASSWORD) db psql -U $(POSTGRES_USER) -d $(PG_DB)

db-down: ## Stop the container, keep the data volume
	docker compose down

db-nuke: ## Stop the container AND DELETE ALL DATA
	@read -p "This deletes the database volume. Type yes to confirm: " a; [ "$$a" = yes ]
	docker compose down -v
