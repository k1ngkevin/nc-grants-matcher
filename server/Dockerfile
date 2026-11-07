# API service: FastAPI + the daily scheduler. Talks to Postgres via DATABASE_URL.
FROM python:3.12-slim
WORKDIR /app/server
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./
ENV DATA_DIR=/data
RUN useradd -r -u 1001 app && mkdir -p /data && chown app /data
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
