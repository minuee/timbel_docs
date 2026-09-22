# mobile-sync-server — 망분리 서버용 이미지
#
# 이 Dockerfile 은 "인터넷 되는 PC"에서만 빌드한다.
# 빌드가 끝나면 결과물(tar)에 python 과 ffmpeg 가 모두 들어가 있으므로
# 망분리 서버는 docker load 만 하면 되고 네트워크를 전혀 타지 않는다.
#
# 빌드는 deploy/build.sh 로 한다. 직접 docker build 를 치지 말 것 —
# ffmpeg 바이너리를 build.sh 가 미리 받아서 컨텍스트에 놓아야 한다.
#
# 이 파일이 네트워크를 타는 곳은 FROM 한 줄뿐이다.
# ffmpeg 는 apt 가 아니라 static 빌드 바이너리를 복사해서 쓴다:
#   - Debian 의 ffmpeg 패키지는 ffplay(GUI 재생기)까지 포함하는 풀빌드라
#     X11·Wayland·Vulkan·SDL2·Mesa·LLVM 등 250여 개 패키지를 끌고 온다.
#     우리는 오디오만 쓰므로 전부 불필요하고 이미지만 두 배가 된다.
#   - static 빌드는 의존성이 없는 단일 바이너리라 훨씬 작고 버전도 최신이다.
#
# BuildKit 전용 문법(syntax 지시자, cache mount)은 일부러 쓰지 않는다.
# syntax 지시자는 빌드할 때 Docker Hub 에서 frontend 이미지를 추가로 받아오는데,
# 사내 빌드 PC 에서 그것까지 막혀 있으면 원인 찾기가 어려워진다.

FROM python:3.11-slim

# build.sh 가 deploy/.ffmpeg/ 에 받아둔 static 바이너리.
# 코드가 요구하는 최소 버전은 4.4 다 (amix 의 normalize= 옵션이 4.4 에서 추가됨).
COPY deploy/.ffmpeg/ffmpeg deploy/.ffmpeg/ffprobe /usr/local/bin/

RUN chmod 0755 /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
 && ffmpeg  -version | head -1 \
 && ffprobe -version | head -1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    RECOG_HOST=0.0.0.0 \
    RECOG_PORT=8080

# 기본 실행 계정. 다만 compose 의 user: 가 이걸 덮어쓴다 — 서버에서는
# 실제 계정(aimm)의 uid:gid 로 돌려야 호스트에서 데이터 파일을 다룰 수 있다.
# 그래서 아래 파일 권한은 "어떤 uid 로 돌아도 되게" 잡아 둔다.
RUN groupadd --system --gid 10001 recog \
 && useradd  --system --uid 10001 --gid 10001 \
             --home-dir /app --shell /usr/sbin/nologin recog

WORKDIR /app

# 기동 로그의 version 필드가 이 파일을 읽는다. 재시작 로그 한 줄로 어느 이미지가
# 도는지 알 수 있어야 하므로 소스와 함께 넣는다.
COPY --chown=recog:recog VERSION ./VERSION

# recog 는 pip 패키지를 하나도 쓰지 않는다 (표준 라이브러리 + ffmpeg).
# 그래서 requirements.txt 도, pip install 도 없다.
COPY --chown=recog:recog src/ ./src/

# 임의의 uid 로 돌려도 소스를 읽을 수 있어야 한다.
RUN chmod -R a+rX /app/src /app/VERSION

# 데이터는 호스트 볼륨에 바인드된다. 컨테이너 안 경로만 만들어 둔다.
# 볼륨을 안 붙이고 띄우는 경우에도 쓰기가 되도록 권한을 열어 둔다.
RUN mkdir -p /var/lib/recog/runtime \
 && chown -R recog:recog /var/lib/recog \
 && chmod -R a+rwX /var/lib/recog

USER recog
EXPOSE 8080

# curl 을 설치하지 않는다. 헬스체크는 이미지에 이미 있는 python 으로 한다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('RECOG_PORT','8080')+'/health',timeout=3)"]

ENTRYPOINT ["python", "-m", "recog"]
CMD ["--data-root", "/var/lib/recog/runtime", "serve"]
