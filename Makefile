.PHONY: install test lint run
install:
	pip install -e ".[dev,ocr]"
test:
	pytest
lint:
	ruff check .
run:
	uvicorn document_core.api:app --reload

