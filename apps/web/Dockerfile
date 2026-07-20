ARG NODE_IMAGE=node:22-trixie-slim@sha256:2d9f5c76c8f4dd36e8f253bee5d828a83a6c09f36188f0b0414325232e0b175d

FROM ${NODE_IMAGE} AS builder

ENV NEXT_TELEMETRY_DISABLED=1 \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:${PATH}

RUN corepack enable && corepack prepare pnpm@10.32.0 --activate

WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN --mount=type=cache,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter @ntc-rag/web...

COPY apps/web apps/web
RUN pnpm --filter @ntc-rag/web build

FROM ${NODE_IMAGE} AS runtime

ENV HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    PORT=3000

WORKDIR /app
COPY --from=builder --chown=node:node /workspace/apps/web/.next/standalone ./
COPY --from=builder --chown=node:node /workspace/apps/web/.next/static ./apps/web/.next/static

USER node
EXPOSE 3000

CMD ["node", "apps/web/server.js"]
