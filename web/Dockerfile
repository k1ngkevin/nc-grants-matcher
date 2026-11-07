# Web service: builds the React site and serves it with nginx, which forwards /api to the api service.
FROM node:22-slim AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . ./
RUN npm run build

FROM nginx:1.27-alpine
# nginx fills ${API_UPSTREAM} into the template at startup (only variables that are set; $host etc. are left alone).
ENV API_UPSTREAM=api:8000
COPY nginx/templates/ /etc/nginx/templates/
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
