# Shortcuts. Работает в git-bash на Windows и в *nix.
# На голой PowerShell используйте poetry-команды напрямую (см. README).

.PHONY: help install run index lint format type test cov check docker docker-run clean

help:
	@echo "TeacherFactory — список задач:"
	@echo "  install     — установить зависимости (poetry install)"
	@echo "  run         — поднять Streamlit на http://localhost:8501"
	@echo "  index       — пересобрать RAG-индекс из docs/"
	@echo "  lint        — ruff check"
	@echo "  format      — ruff format + ruff check --fix"
	@echo "  type        — mypy"
	@echo "  test        — pytest"
	@echo "  cov         — pytest + coverage report"
	@echo "  check       — lint + type + test (то же, что в CI)"
	@echo "  docker      — собрать Docker-образ"
	@echo "  docker-run  — поднять docker-compose"
	@echo "  clean       — удалить кэши"

install:
	poetry install

run:
	poetry run streamlit run src/teacherfactory/app.py

index:
	poetry run python -m teacherfactory.indexer

lint:
	poetry run ruff check src tests

format:
	poetry run ruff format src tests
	poetry run ruff check src tests --fix

type:
	poetry run mypy src/teacherfactory

test:
	poetry run pytest

cov:
	poetry run pytest --cov --cov-report=term-missing

check: lint type test

docker:
	docker build -t teacherfactory:latest .

docker-run:
	docker compose up --build

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
