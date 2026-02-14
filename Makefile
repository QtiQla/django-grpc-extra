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

install-linters: ## Install dependencies for linters
	make clean
	pip install ruff
	pip install mypy
	pip install pre-commit
	pip install django-stubs
	pip install django-stubs-ext
	pip install types-python-dateutil

install-test: ## Install dependencies for tests
	make clean
	pip install pytest
	pip install pytest-cov
	pip install pytest-django

format: ## Run code formatters
	make clean
	ruff format grpc_extra tests
	ruff check --fix grpc_extra tests

lint: ## Run code linters
	make clean
	ruff check grpc_extra tests
	mypy grpc_extra

docs-serve: ## Serve documentation locally
	mkdocs serve

docs-build: ## Build documentation
	mkdocs build

docs-deploy: ## Deploy documentation to GitHub Pages
	mkdocs gh-deploy
	isort --check grpc_extra
	flake8 grpc_extra
	make mypy

test: ## Run tests
	make clean
	pytest tests --reuse-db

test-fresh: ## Run tests with fresh database
	make clean
	pytest tests --create-db

test-cov: ## Run tests with coverage
	make clean
	pytest --cov=grpc_extra --cov-report term-missing --cov-fail-under=85 tests --reuse-db

check-all: ## precommit check_all
	pre-commit run --all-files
