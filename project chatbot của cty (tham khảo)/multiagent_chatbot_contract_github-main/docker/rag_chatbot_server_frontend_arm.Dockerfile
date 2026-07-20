FROM --platform=linux/arm64 node:22-bookworm-slim AS builder

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM --platform=linux/arm64 node:22-bookworm-slim AS runner

WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/package*.json ./
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.mjs ./next.config.mjs

RUN npm ci --omit=dev

EXPOSE 3000
CMD ["npm", "run", "start"]
