# Minio

## Get Started

```Shell
$ docker login ghcr.io -u ${githubUser}
$ docker pull ghcr.io/timbel-timblo-onpremise/minio:latest
```

## Docker-compose 파일 수정

```Shell
$ vim docker-compose.yml
```

#### 적용 가능 환경 변수 리스트

> 아래 옵션은 개발서버 기준 설정으로 기본 `minio/minio` 이미지를 따라감

```Dockerfile
      BUCKET_NAME: "default.timblo.io"
      PUB_BUCKET_NAME: "default.public.timblo.io"

      MINIO_ROOT_USER: admin
      MINIO_ROOT_PASSWORD: "admin"
      MINIO_REGION: ap-northeast-2
      MINIO_NOTIFY_WEBHOOK_ENABLE: "off"
      MINIO_NOTIFY_AMQP_ENALBE: "off"
      MINIO_VOLUMES: /data/minio_data
      MINIO_CONSOLE_ADDRESS: ":9090"


```

## 실행 및 환경 변수 확인

```Shell
$ docker-compose up -d
```

### 주의

> 실행 전 docker-compose config 와 같은 명령으로 환경 변수 적용 확인
