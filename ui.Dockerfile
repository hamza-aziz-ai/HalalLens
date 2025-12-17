FROM node:20-alpine

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app/ui

COPY ui/package.json ui/package-lock.json ./

RUN npm ci

COPY ui/ ./

ARG NEXT_PUBLIC_HALAL_API_BASE_URL=http://api:8001
ENV NEXT_PUBLIC_HALAL_API_BASE_URL=${NEXT_PUBLIC_HALAL_API_BASE_URL}

RUN npm run build && npm install --global serve

EXPOSE 3000

CMD ["serve", "-s", "out", "-l", "3000"]
