FROM docker.timblo.io/master-alpine:latest AS builder

WORKDIR /usr/src/app

COPY ["package*.json", "./"]
COPY [".npmrc", "./"]

RUN npm ci --omit=dev

FROM docker.timblo.io/master-alpine:latest

WORKDIR /usr/src/app

COPY ["package*.json", "./"]
COPY ["dist/", "./"]
COPY ["assets", "./assets"]
COPY ["src/docs/", "./docs/"]
COPY ["src/configs/swagger*", "./configs/"]

COPY --from=builder ["/usr/src/app/node_modules", "./node_modules"]

ENV PORT=9012
ENV SYS_NAME=be-master-service
ENV APP_NAME=master

ENTRYPOINT ["sh", "-c", "node ./utils/fetchEnv.js && pm2-docker ecosystem.config.cjs"]