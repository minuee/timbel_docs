# Locus-KMS frontend — nginx static 컨테이너 (V1 MVP, build step 없음).
# build context 는 ./frontend (root .dockerignore 가 frontend/ 를 막으므로 우회).
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY . /usr/share/nginx/html
# 빌드 메타파일은 정적 서빙에서 제외 (config 노출 방지).
RUN rm -f /usr/share/nginx/html/Dockerfile \
          /usr/share/nginx/html/nginx.conf

EXPOSE 80
