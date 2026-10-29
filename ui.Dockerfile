# Two stages: Node builds the static export; the runtime image holds only the
# built files and a small static file server. No Node.js, no node_modules, no
# Next.js server at runtime (the export needs none), and it runs unprivileged.

FROM node:24-alpine AS build

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app/ui

COPY ui/package.json ui/package-lock.json ./

RUN npm ci

COPY ui/ ./

# Default: same origin behind Caddy (/api/* -> API). Override for other setups.
ARG NEXT_PUBLIC_HALAL_API_BASE_URL=/api
ENV NEXT_PUBLIC_HALAL_API_BASE_URL=${NEXT_PUBLIC_HALAL_API_BASE_URL}

RUN npm run build

FROM caddy:2.11.6-alpine

# Take the base image's Alpine security fixes at build time (e.g. brotli-libs
# CVE-2026-111497 failed the v0.7.0 publish scan), so the image does not wait
# for the next Caddy release.
RUN apk upgrade --no-cache

# Caddy keeps its state under XDG directories; /tmp is writable for any user.
ENV XDG_CONFIG_HOME=/tmp/caddy-config \
    XDG_DATA_HOME=/tmp/caddy-data

COPY ui/Caddyfile.static /etc/caddy/Caddyfile
COPY --from=build /app/ui/out /srv
COPY LICENSE /srv/LICENSE.txt

USER 10001:10001

EXPOSE 3000

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
