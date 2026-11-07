# One container: builds the React site, then serves it + the API with uvicorn.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/server
COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ ./
COPY --from=web /web/dist /app/web/dist
ENV WEB_DIST=/app/web/dist DATA_DIR=/data APP_ENV=production AUTH_MODE=entra
VOLUME ["/data"]
EXPOSE 8000
RUN useradd -r -u 1001 app && mkdir -p /data && chown app /data
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
