#!/usr/bin/env python3

"""
Docker Hub에서 Uptime Kuma 이미지를 다운로드하여
docker load 형식의 tar.gz 파일로 변환하는 스크립트
"""

import json
import os
import tarfile
import hashlib
import sys
import urllib.request
import urllib.error
from pathlib import Path

def download_file(url, output_path):
    """URL에서 파일 다운로드"""
    print(f"  다운로드: {url}")
    try:
        urllib.request.urlretrieve(url, output_path)
        return True
    except Exception as e:
        print(f"  ❌ 실패: {e}")
        return False

def get_image_manifest(image, tag):
    """Docker Hub에서 이미지 매니페스트 조회"""
    url = f"https://registry.hub.docker.com/v2/{image}/manifests/{tag}"
    headers = {
        'Accept': 'application/vnd.docker.distribution.manifest.v2+json'
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ 매니페스트 조회 실패: {e}")
        return None

def get_auth_token():
    """Docker Hub 인증 토큰 조회"""
    url = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:louislam/uptime-kuma:pull"
    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
            return data.get('token')
    except:
        return None

def download_blob(image, digest, output_path, token=None):
    """Docker Hub에서 blob 다운로드"""
    url = f"https://registry-1.docker.io/v2/{image}/blobs/{digest}"
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(output_path, 'wb') as f:
                f.write(response.read())
        return True
    except Exception as e:
        print(f"  ❌ Blob 다운로드 실패: {digest[:12]}... - {e}")
        return False

def prepare_offline_image(image_name, tag, output_file, architecture):
    """오프라인 이미지 패키지 준비"""
    print(f"\n{'='*60}")
    print(f"Uptime Kuma 이미지 준비: {image_name}:{tag} ({architecture})")
    print(f"{'='*60}\n")

    # 1. 이미지 정보 조회
    print("[1/5] Docker Hub에서 이미지 정보 조회...")
    manifest = get_image_manifest(image_name, tag)
    if not manifest:
        print("❌ 이미지를 찾을 수 없습니다.")
        return False

    # 다중 아키텍처 지원 확인
    if 'manifests' in manifest:
        # Manifest List (다중 아키텍처)
        for m in manifest['manifests']:
            if m['platform']['architecture'] == architecture:
                manifest = get_image_manifest(image_name, m['digest'])
                break

    print("✅ 이미지 정보 조회 완료")

    # 2. 필요한 파일 목록 확인
    print("\n[2/5] 필요한 레이어 확인...")
    layers = manifest.get('layers', [])
    config_digest = manifest.get('config', {}).get('digest')

    print(f"  레이어 수: {len(layers)}")
    print(f"  Config: {config_digest[:12]}...")
    print("✅ 확인 완료")

    # 3. 인증 토큰 획득
    print("\n[3/5] Docker Hub 인증...")
    token = get_auth_token()
    if not token:
        print("⚠️  토큰 획득 실패. 공개 레지스트리로 시도합니다.")
    else:
        print("✅ 인증 성공")

    # 4. 레이어 및 config 다운로드
    print("\n[4/5] 이미지 레이어 다운로드...")
    temp_dir = Path(f".tmp_image_{architecture}")
    temp_dir.mkdir(exist_ok=True)

    try:
        # Config 다운로드
        config_path = temp_dir / "config.json"
        if not download_blob(image_name, config_digest, config_path, token):
            print("❌ Config 다운로드 실패")
            return False

        # 레이어 다운로드
        layer_files = []
        for i, layer in enumerate(layers):
            digest = layer['digest']
            layer_path = temp_dir / f"layer_{i}.tar.gz"
            print(f"  [{i+1}/{len(layers)}] {digest[:12]}...", end="")

            if download_blob(image_name, digest, layer_path, token):
                layer_files.append((layer_path, digest, layer['mediaType']))
                print(" ✅")
            else:
                print(" ❌")
                return False

        print("✅ 다운로드 완료")

        # 5. docker load 형식의 tar 파일로 조립
        print("\n[5/5] docker load 형식으로 조립...")

        with tarfile.open(output_file, 'w:gz') as tar:
            # manifest.json 생성
            manifest_data = [{
                "Config": "config.json",
                "RepoTags": [f"{image_name}:latest"],
                "Layers": [f"layer_{i}.tar.gz" for i in range(len(layer_files))]
            }]

            manifest_json = json.dumps(manifest_data).encode('utf-8')
            manifest_tarinfo = tarfile.TarInfo(name="manifest.json")
            manifest_tarinfo.size = len(manifest_json)
            tar.addfile(manifest_tarinfo, fileobj=__import__('io').BytesIO(manifest_json))

            # config 추가
            with open(config_path, 'rb') as f:
                config_data = f.read()
            config_tarinfo = tarfile.TarInfo(name="config.json")
            config_tarinfo.size = len(config_data)
            tar.addfile(config_tarinfo, fileobj=__import__('io').BytesIO(config_data))

            # 레이어들 추가
            for i, (layer_path, digest, media_type) in enumerate(layer_files):
                layer_tar_path = f"layer_{i}.tar.gz"
                tar.add(layer_path, arcname=layer_tar_path)

        print(f"✅ 조립 완료: {output_file}")

        # 정리
        import shutil
        shutil.rmtree(temp_dir)

        # 파일 크기 확인
        file_size = os.path.getsize(output_file)
        size_mb = file_size / (1024 * 1024)
        print(f"📦 파일 크기: {size_mb:.1f}MB\n")

        return True

    except Exception as e:
        print(f"❌ 오류: {e}")
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        return False

def main():
    images_dir = Path("images")
    images_dir.mkdir(exist_ok=True)

    # amd64 버전 준비
    amd64_output = images_dir / "uptime-kuma-latest-amd64.tar.gz"
    if not amd64_output.exists():
        if not prepare_offline_image("louislam/uptime-kuma", "latest", str(amd64_output), "amd64"):
            print("❌ amd64 이미지 준비 실패")
            sys.exit(1)
    else:
        print(f"✅ {amd64_output.name} 이미 존재")

    # arm64 버전 준비
    arm64_output = images_dir / "uptime-kuma-latest-arm64.tar.gz"
    if not arm64_output.exists():
        if not prepare_offline_image("louislam/uptime-kuma", "latest", str(arm64_output), "arm64"):
            print("❌ arm64 이미지 준비 실패")
            sys.exit(1)
    else:
        print(f"✅ {arm64_output.name} 이미 존재")

    print("\n" + "="*60)
    print("✅ 모든 이미지 준비 완료!")
    print("="*60)
    print("\n다음 단계:")
    print("  cd ..")
    print("  tar czf uptime-kuma-offline.tar.gz uptime-kuma-offline-template/")
    print("\n생성된 패키지를 서버로 전달하세요.")

if __name__ == "__main__":
    main()
