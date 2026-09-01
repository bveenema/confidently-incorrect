PYTHON ?= python
SHA := $(shell git rev-parse --short HEAD 2>nul)
ifeq ($(SHA),)
SHA := dev
endif

.PHONY: test test-integration lint fmt build dry-run run

test:
	$(PYTHON) -m pytest tests -m "not integration"

test-integration:
	$(PYTHON) -m pytest tests -m integration

lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m mypy

fmt:
	$(PYTHON) -m ruff format src tests

build:
	podman build -t ci:$(SHA) -f Containerfile .

dry-run:
	@echo not implemented: dry-run
	@exit 2

run:
	@echo not implemented: $(TASK)
	@exit 2
