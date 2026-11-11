# Audio Sync Merge Service MVP

Greenfield Python MVP for asynchronous meeting-audio alignment and export.

## What it does

- creates upload sessions
- stores up to 5 participant recordings per session
- canonicalizes mixed input formats to 48kHz mono PCM via `ffmpeg`
- estimates per-track offset and simple drift correction against a reference track
- exports aligned tracks, a listening mixdown, and a manifest suitable for downstream STT handoff
- keeps explicit non-goals out of scope: real-time, diarization/identification, manual editing UI, video sync

## API

The stdlib WSGI service exposes:

- `POST /sessions`
- `POST /sessions/{id}/files?participant_id=p1&filename=a.wav`
- `POST /sessions/{id}/process`
- `GET /sessions/{id}`
- `GET /sessions/{id}/artifacts`

`POST /sessions/{id}/files` accepts raw file bytes in the request body for MVP simplicity.

## Run

```bash
PYTHONPATH=src python3 -m recog --data-root .runtime serve
```

## Generate and process a synthetic verification corpus

```bash
PYTHONPATH=src python3 -m recog --data-root .runtime generate-fixture --output /tmp/fixture --tracks 3
PYTHONPATH=src python3 -m recog --data-root .runtime process-fixture --input /tmp/fixture
```

Override fixture duration when you need a larger synthetic session:

```bash
PYTHONPATH=src python3 -m recog --data-root .runtime generate-fixture --output /tmp/fixture --tracks 5 --duration-seconds 60
```

Run a repeatable synthetic load probe and emit a prefilled listening-review sheet:

```bash
PYTHONPATH=src python3 tools/run_load_probe.py verification/evidence/$(date -u +%Y%m%dT%H%M%SZ)/probe --tracks 5 --duration-seconds 60
```

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall src tests
```

## Docker

Local image build (BuildKit required):

```bash
DOCKER_BUILDKIT=1 docker build -t recog-backend:dev .
docker run --rm -p 28080:8080 -v "$PWD/.runtime:/var/lib/recog/runtime" recog-backend:dev
curl http://127.0.0.1:28080/health
```

Compose-based bring-up (mirrors the CI deploy):

```bash
cp deploy/.env.recog.example .env.recog
cp deploy/docker-compose.yml .
docker compose --env-file .env.recog up -d
```

## CI / CD

GitLab pipeline lives in `.gitlab-ci.yml`.

- **Trigger branch**: `skHynix` (dev stays on `main`; push to `skHynix` to build & deploy)
- **Image**: `ghcr.io/timbel-timblo-onpremise/recog-backend:skHynix-<sha>` (+ `skHynix-latest`)
- **Runner**: shared timblo runner (shell executor on the deploy host)
- **Deploy path**: `/home/jwpark/timblo-hynix/recog-backend` (compose + `.env.recog` + `runtime/`)

One-time setup on the deploy host:

```bash
sudo mkdir -p /home/jwpark/timblo-hynix/recog-backend/runtime
sudo cp deploy/.env.recog.example /home/jwpark/timblo-hynix/recog-backend/.env.recog
# edit .env.recog if ports/registry need to change
```

Subsequent pushes to `skHynix` will:
1. build the image with `--cache-from` the previous `skHynix-latest`
2. push `skHynix-<sha>` and `skHynix-latest` to ghcr
3. `sed` `RECOG_VERSION` in `.env.recog` and `docker compose up -d --no-deps recog-backend`
4. verify `/health` returns 200
