.PHONY: install test lint migrate run
install:
	pip install -e ".[dev,ocr]"
test:
	pytest
lint:
	ruff check .
migrate:
	alembic upgrade head
run:
	uvicorn document_core.api:app --reload
