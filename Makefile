# Makefile for SGLang-Omni Qwen3-TTS 0.6B deployment

.PHONY: help build up down logs shell test health openapi clean

COMPOSE_FILE ?= docker-compose.yml
IMAGE_TAG ?= qwen3-tts-server:latest

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

build: ## Build the Docker image
	docker build -t $(IMAGE_TAG) .

up: ## Start the TTS server with docker-compose
	docker compose -f $(COMPOSE_FILE) up -d

down: ## Stop and remove containers
	docker compose -f $(COMPOSE_FILE) down

logs: ## Tail container logs
	docker compose -f $(COMPOSE_FILE) logs -f

shell: ## Open a shell inside the running container
	docker exec -it qwen3-tts-server /bin/bash

test: ## Run the test client (list voices)
	python tests/test_client.py --url http://localhost:8000 list

health: ## Check server health
	curl -fsS http://localhost:8000/health

openapi: ## Fetch OpenAPI spec from the running server
	python scripts/generate-openapi.py http://localhost:8000 > openapi.json

clean: ## Remove containers, images, and volumes
	docker compose -f $(COMPOSE_FILE) down -v --rmi local
	docker rmi $(IMAGE_TAG) || true
