# Stage 1: dependencies from the committed lockfile.
FROM node:24-alpine AS deps

# Next.js collects anonymous usage telemetry unless this opt-out is set.
ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY package*.json ./
RUN npm ci

# Stage 2: the production build. Next writes a standalone server bundle.
FROM deps AS builder

COPY . .
RUN npm run build

# Stage 3: the runtime image for everyday use. Server bundle and static assets
# only: no sources, no dev dependencies, no build toolchain, non-root user.
FROM node:24-alpine AS runner

ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app
RUN addgroup -S localdoc && adduser -S -G localdoc -u 10001 localdoc

COPY --from=builder --chown=localdoc:localdoc /app/.next/standalone ./
COPY --from=builder --chown=localdoc:localdoc /app/.next/static ./.next/static

USER localdoc
EXPOSE 3000
CMD ["node", "server.js"]

# Stage 4: the development image, and the default build target. Sources and
# the full dependency tree, for the bind-mounted Compose service.
FROM deps AS dev

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
