FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt requirements-connectors.txt ./
RUN pip install --no-cache-dir -r requirements-connectors.txt
COPY src ./src
COPY static ./static
COPY scripts ./scripts
RUN mkdir -p /app/data
ENV PYTHONPATH=/app/src GAME_DB_PATH=/app/data/game.db GAME_DEMO_DATA=false GAME_AUTH_MODE=password PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "game.main:app", "--host", "0.0.0.0", "--port", "8000"]
