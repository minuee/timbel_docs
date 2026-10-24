"""Turn an audio file into the encrypted PCM chunks the app uploads to master-api.

master-api /contents/upload/encryption/files expects what the app sends:
  - 16 kHz / mono / s16le PCM, split into 3-minute chunks
  - each chunk AES-256-CBC (PKCS7) encrypted on its own, key/IV taken as UTF-8 bytes
  - chunk names end with _<index>.pcm, index from 0 (server sorts and checks by it)

Key/IV: env AES_KEY / AES_IV (the server's consul values), or else the group
recording key in the app source (groupAudioEncKey / groupAudioEncIv).
Needs ffmpeg and openssl on PATH.

usage: python3 encrypt_for_upload.py <audio> <out_dir> [--app-const PATH]
"""

import os
import re
import subprocess
import sys
from pathlib import Path

SR = 16000
CHUNK_SEC = 180  # app: 1 chunk = 3 minutes
APP_CONST = Path(__file__).resolve().parents[2] / "mobileapp/lib/constants/app_const.dart"


def load_key(app_const):
    key, iv = os.environ.get("AES_KEY"), os.environ.get("AES_IV")
    if key and iv:
        return key, iv
    src = Path(app_const).read_text(encoding="utf-8")
    key = re.search(r"groupAudioEncKey\s*=\s*'([^']*)'", src)
    iv = re.search(r"groupAudioEncIv\s*=\s*'([^']*)'", src)
    if not key or not iv:
        sys.exit(f"groupAudioEncKey/Iv not found in {app_const}; set AES_KEY and AES_IV")
    return key.group(1), iv.group(1)


def main():
    args = sys.argv[1:]
    app_const = APP_CONST
    if "--app-const" in args:
        i = args.index("--app-const")
        app_const = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    audio, out = Path(args[0]), Path(args[1])

    key, iv = load_key(app_const)
    key_b, iv_b = key.encode("utf-8"), iv.encode("utf-8")
    if len(key_b) != 32 or len(iv_b) != 16:
        sys.exit(f"key must be 32 bytes and IV 16 bytes (got {len(key_b)} / {len(iv_b)})")

    pcm = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(audio), "-ac", "1", "-ar", str(SR),
         "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        check=True, capture_output=True).stdout

    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("encrypted_audio_*.pcm"):
        old.unlink()
    step = SR * 2 * CHUNK_SEC
    chunks = [pcm[i:i + step] for i in range(0, len(pcm), step)]
    for n, chunk in enumerate(chunks):
        subprocess.run(
            ["openssl", "enc", "-aes-256-cbc", "-K", key_b.hex(), "-iv", iv_b.hex(),
             "-out", str(out / f"encrypted_audio_{n}.pcm")],
            input=chunk, check=True)
    print(f"{audio.name}: {len(pcm) / SR / 2:.1f}s -> {out}  totalNum={len(chunks)}")


if __name__ == "__main__":
    main()
