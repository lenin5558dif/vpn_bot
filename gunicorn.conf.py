import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('BACKEND_PORT', '8000')}"
workers = int(os.getenv("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2 + 1, 4)))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
