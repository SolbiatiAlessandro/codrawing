FROM docker.io/library/python:3.12-slim

RUN pip install --no-cache-dir fastapi==0.115.5 uvicorn[standard]==0.34.2 websockets==15.0.1

ENV PYTHONPATH=/app
WORKDIR /app
COPY codrawing /app/codrawing

CMD ["python", "-m", "codrawing.game.server"]
