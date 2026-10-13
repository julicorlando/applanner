FROM node:22-alpine
RUN apk add --no-cache git
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY server.js tenant-server.js logging.js ./
RUN mkdir -p /app/session && chown -R node:node /app
USER node
EXPOSE 3100
CMD ["node","server.js"]
