.PHONY: help docs
.DEFAULT_GOAL := help

help:
	@fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'


clean: ## Removing cached python compiled files
	find . -type f -name "*.pyc" -not -path "./.venv/*" -delete
	find . -type f -name "*.pyo" -not -path "./.venv/*" -delete
	find . -type f -name "*~" -not -path "./.venv/*" -delete
	rm -rf .ruff_cache
	find . -type d -name "__pycache__" -not -path "./.venv/*" -prune -exec rm -rf {} +
	rm -rf .mypy_cache .pytest_cache .coverage htmlcov

install:clean ## Install dependencies
	pip install -r requirements.txt
	flit install --symlink


install-full:install ## Install dependencies
	pre-commit install -f

format: ## Run code formatters
	make clean
	ruff format grpc_extra tests
	ruff check --fix grpc_extra tests

lint: ## Run code linters
	make clean
	ruff check grpc_extra tests
	mypy grpc_extra

doc-deploy:clean ## Run Deploy Documentation
	mkdocs gh-deploy --force

doc-serve: ## Launch doc local server
	mkdocs serve

test:clean ## Run tests
	pytest tests

test-cov:clean ## Run tests with coverage
	pytest --cov=grpc_extra --cov-report term-missing tests

