FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html tsconfig.json tsconfig.node.json vite.config.ts ./
COPY src ./src

RUN npm run build

FROM node:20-alpine

WORKDIR /app

RUN npm install -g vite@5.4.21

COPY --from=build /app/dist ./dist

EXPOSE 15000

CMD ["vite", "preview", "--host", "0.0.0.0", "--port", "15000"]
