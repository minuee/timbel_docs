"""빌드된 이미지가 실제로 동작하는지 컨테이너 안에서 확인한다.

이미지에 들어가지 않는다. build.sh 가 docker cp 로 넣고 docker exec 로 돌린다.

확인하는 것:
  1. python / ffmpeg / ffprobe 가 있고 버전이 요구사항을 만족하는가
  2. /health 가 200 인가
  3. 실제 음성 두 개를 올려 병합이 DONE 까지 가는가
  4. 결과 파일을 내려받을 수 있고 재생 가능한 오디오인가

표준 라이브러리만 쓴다 (컨테이너에 pip 패키지가 없으므로).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

PORT = os.environ.get("RECOG_PORT", "8080")
BASE = f"http://127.0.0.1:{PORT}"
WORK = "/tmp/smoke"

#: 코드가 쓰는 필터 중 가장 최신이 amix 의 normalize= 이고 4.4 에서 추가됐다.
MIN_FFMPEG = (4, 4)
#: models.py 의 `from datetime import UTC` 가 3.11+ 를 요구한다.
MIN_PYTHON = (3, 11)


def step(text: str) -> None:
    print(f"  [smoke] {text}", flush=True)


def fail(text: str) -> None:
    print(f"  [smoke] 실패: {text}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def run(cmd: list[str]) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        fail(f"{cmd[0]} 실행 실패\n{done.stderr.strip()}")
    return done.stdout + done.stderr


def check_tools() -> None:
    if sys.version_info < MIN_PYTHON:
        fail(f"python {'.'.join(map(str, MIN_PYTHON))}+ 필요, 이미지는 {sys.version.split()[0]}")
    step(f"python {sys.version.split()[0]}")

    for tool in ("ffmpeg", "ffprobe"):
        banner = run([tool, "-version"]).splitlines()[0]
        found = re.search(r"version\s+n?(\d+)\.(\d+)", banner)
        if not found:
            fail(f"{tool} 버전을 읽지 못함: {banner}")
        version = (int(found.group(1)), int(found.group(2)))
        if version < MIN_FFMPEG:
            fail(f"{tool} {'.'.join(map(str, MIN_FFMPEG))}+ 필요, 이미지는 {'.'.join(map(str, version))}")
        step(f"{tool} {'.'.join(map(str, version))}")

    # 코드가 실제로 쓰는 필터가 이 빌드에 포함되어 있는지 직접 확인한다.
    # 버전만 보고 넘어가면 최소 빌드(--disable-filter)에서 런타임에 터진다.
    filters = run(["ffmpeg", "-hide_banner", "-filters"])
    for name in ("amix", "adelay", "alimiter", "apad", "atrim", "aresample", "volume"):
        if not re.search(rf"\s{name}\s", filters):
            fail(f"ffmpeg 에 {name} 필터가 없음")
    step("필요한 ffmpeg 필터 7종 모두 존재")


def wait_health(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=3) as response:
                if response.status == 200:
                    step(f"/health 200 ({response.read(200).decode('utf-8', 'replace').strip()})")
                    return
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
        time.sleep(1)
    fail(f"/health 가 {timeout:.0f}초 안에 응답하지 않음 ({last})")


def make_audio() -> list[str]:
    os.makedirs(WORK, exist_ok=True)
    paths = []
    # 서로 다른 주파수의 3초짜리 사인파 두 개. 섞이면 둘 다 들어 있어야 한다.
    for index, freq in enumerate((440, 660), start=1):
        path = f"{WORK}/p{index}.flac"
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=3:sample_rate=48000",
            "-ac", "1", path,
        ])
        paths.append(path)
    step(f"테스트 음성 {len(paths)}개 생성 (440Hz, 660Hz / 3초)")
    return paths


def post_upload(paths: list[str]) -> str:
    boundary = uuid.uuid4().hex
    body = bytearray()
    for key, value in (("roomNo", "smoke-test"), ("align", "none"), ("format", "flac")):
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()
    for path in paths:
        with open(path, "rb") as handle:
            blob = handle.read()
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="{os.path.basename(path)}"\r\n'
            f"Content-Type: audio/flac\r\n\r\n"
        ).encode()
        body += blob + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    request = urllib.request.Request(
        f"{BASE}/v1/merge/upload",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        fail(f"POST /v1/merge/upload {exc.code}\n{exc.read().decode('utf-8', 'replace')}")
    job_id = payload.get("jobId")
    if not job_id:
        fail(f"응답에 jobId 가 없음: {payload}")
    step(f"병합 접수됨 jobId={job_id} status={payload.get('status')}")
    return job_id


def wait_done(job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    seen = None
    while time.time() < deadline:
        with urllib.request.urlopen(f"{BASE}/v1/merge/{job_id}", timeout=10) as response:
            payload = json.loads(response.read())
        status = payload.get("status")
        if status != seen:
            step(f"status={status}")
            seen = status
        if status == "DONE":
            return payload
        if status == "FAILED":
            fail(f"병합 실패: {json.dumps(payload, ensure_ascii=False)}")
        time.sleep(2)
    fail(f"{timeout:.0f}초 안에 끝나지 않음 (마지막 status={seen})")
    return {}


def check_result(job_id: str) -> None:
    out = f"{WORK}/merged.flac"
    with urllib.request.urlopen(f"{BASE}/v1/merge/{job_id}/download", timeout=60) as response:
        blob = response.read()
    if len(blob) < 1024:
        fail(f"결과 파일이 너무 작음 ({len(blob)} bytes)")
    with open(out, "wb") as handle:
        handle.write(blob)

    probe = json.loads(run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", out
    ]))
    stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
    if stream is None:
        fail("결과 파일에 오디오 스트림이 없음")
    duration = float(probe["format"].get("duration") or 0)
    if duration < 2.5:
        fail(f"결과 길이가 비정상 ({duration:.2f}초, 3초여야 함)")
    step(
        f"결과 확인: {len(blob):,} bytes / {stream.get('codec_name')} / "
        f"{stream.get('sample_rate')}Hz / {duration:.2f}초"
    )


def main() -> None:
    print("=== 이미지 스모크 테스트 ===", flush=True)
    check_tools()
    wait_health()
    job_id = post_upload(make_audio())
    wait_done(job_id)
    check_result(job_id)
    print("=== 통과 ===", flush=True)


if __name__ == "__main__":
    main()
