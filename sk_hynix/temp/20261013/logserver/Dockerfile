# pcapp-log-server — 망분리 서버용 이미지
#
# 이 Dockerfile 은 "인터넷 되는 PC"에서만 빌드한다. 빌드는 deploy/build.sh 로 한다.
# 결과물(tar)에 node 와 소스가 모두 들어가 있으므로 망분리 서버는 docker load 만 하면 된다.
#
# 네트워크를 타는 곳은 FROM 한 줄뿐이다.
# 서버가 외부 패키지를 하나도 쓰지 않아서 npm install 단계가 없다.
#
# BuildKit 전용 문법(syntax 지시자, cache mount)은 일부러 쓰지 않는다.
# syntax 지시자는 빌드할 때 frontend 이미지를 추가로 받아오는데, 그것까지 막혀 있으면 원인 찾기가 어렵다.

FROM node:20-alpine

ENV NODE_ENV=production \
    PORT=9996 \
    HOST=0.0.0.0 \
    LOG_DIR=/var/lib/pcapp-log

WORKDIR /app

# 기동 로그의 version 이 이 파일을 읽는다. 재시작 로그 한 줄로 어느 이미지가 도는지 알 수 있게.
COPY VERSION ./VERSION
COPY package.json ./package.json
COPY src/ ./src/

# compose 의 user: 가 서버 계정(aimm)의 uid 로 덮어쓴다. 어떤 uid 로 돌아도 되게 권한을 열어 둔다.
#   /app            읽기만
#   /var/lib/pcapp-log  쓰기 (호스트 폴더가 바인드되는 자리)
RUN chmod -R a+rX /app \
 && mkdir -p /var/lib/pcapp-log \
 && chmod -R a+rwX /var/lib/pcapp-log

# node 이미지의 기본 계정(uid 1000). 서버에서는 compose 가 덮어쓴다.
USER node
EXPOSE 9996

# curl 을 설치하지 않는다. 헬스체크는 이미지에 이미 있는 node 로 한다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:'+(process.env.PORT||9996)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

CMD ["node", "src/server.js"]
