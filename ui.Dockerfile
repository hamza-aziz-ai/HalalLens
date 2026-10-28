FROM node:20-alpine

ENV NEXT_TELEMETRY_DISABLED=1 \
    TZ=Asia/Kolkata

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app/ui

COPY ui/package.json ui/package-lock.json ./

RUN npm ci

COPY ui/ ./

# Default: same origin behind Caddy (/api/* -> API). Override for other setups.
ARG NEXT_PUBLIC_HALAL_API_BASE_URL=/api
ENV NEXT_PUBLIC_HALAL_API_BASE_URL=${NEXT_PUBLIC_HALAL_API_BASE_URL}

RUN npm run build && npm install --global serve

COPY ui/docker-entrypoint.sh /entrypoint.sh
# A Windows checkout (core.autocrlf) gives the script CRLF endings, and the
# kernel then reports "/entrypoint.sh: not found". Normalise in the image.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 3000

CMD ["/entrypoint.sh"]
