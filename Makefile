.PHONY: demo test test-unit test-integration benchmark lint typecheck frontend-check frontend-build check up down

PYTHON ?= python3

demo:
	./scripts/quick_demo.sh

test: test-unit

test-unit:
	$(PYTHON) -m pytest -q -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=80

lint:
	$(PYTHON) -m ruff check app tests scripts

typecheck:
	$(PYTHON) -m mypy app scripts

frontend-check:
	cd frontend && npm run check

frontend-build:
	cd frontend && npm run build

check: lint typecheck test-unit frontend-check

test-integration:
	RUN_INTEGRATION=1 EXECUTION_MODE=celery \
		DATABASE_URL=mysql+pymysql://reliability_lab:reliability_lab_dev@127.0.0.1:3307/reliability_lab \
		CELERY_BROKER_URL=redis://127.0.0.1:6380/0 \
		CELERY_RESULT_BACKEND=redis://127.0.0.1:6380/0 \
		$(PYTHON) -m pytest -q -m integration

benchmark:
	EXECUTION_MODE=celery \
		DATABASE_URL=mysql+pymysql://reliability_lab:reliability_lab_dev@127.0.0.1:3307/reliability_lab \
		CELERY_BROKER_URL=redis://127.0.0.1:6380/0 \
		CELERY_RESULT_BACKEND=redis://127.0.0.1:6380/0 \
		$(PYTHON) -m scripts.run_concurrent_benchmark --runs 40 --concurrency 8 --worker-concurrency 4

up:
	docker compose up --build

down:
	docker compose down -v
