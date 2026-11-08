#!/usr/bin/env python3
"""
AES256-CBC 복호화 스크립트
Dart 코드와 동일한 방식으로 암호화된 오디오 세그먼트 파일을 복호화합니다.

사용법: python aes256_decrypt.py <encrypted_file>
"""

import sys
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import struct

# Dart 코드와 동일한 키/IV (UTF-8 문자열을 바이트로 변환)
# Dart: Key.fromUtf8('b7671acf046542c4848d6162ee9733cc')
# Dart: IV.fromUtf8('baf766f829f8489a')
KEY_UTF8 = b'b7671acf046542c4848d6162ee9733cc'  # 32바이트
IV_UTF8 = b'baf766f829f8489a'                    # 16바이트

def decrypt_aes256_cbc(encrypted_file_path):
    """
    AES256-CBC로 암호화된 파일을 복호화
    
    Dart 코드와 동일한 방식:
    - 키: UTF-8 문자열 'b7671acf046542c4848d6162ee9733cc' (32바이트)
    - IV: UTF-8 문자열 'baf766f829f8489a' (16바이트)
    - 모드: CBC
    """
    
    if not os.path.exists(encrypted_file_path):
        raise FileNotFoundError(f"암호화된 파일을 찾을 수 없습니다: {encrypted_file_path}")
    
    # 파일 읽기
    with open(encrypted_file_path, 'rb') as f:
        encrypted_data = f.read()
    
    if len(encrypted_data) < 16:  # 최소 크기: IV(16바이트)
        raise ValueError("파일 크기가 너무 작습니다. 올바른 암호화 파일이 아닙니다.")
    
    print(f"파일 크기: {len(encrypted_data)} 바이트")
    print(f"키 (UTF-8): {KEY_UTF8}")
    print(f"IV (UTF-8): {IV_UTF8}")
    
    try:
        # AES256-CBC 복호화 (Dart 코드와 동일)
        cipher = Cipher(algorithms.AES(KEY_UTF8), modes.CBC(IV_UTF8), backend=default_backend())
        decryptor = cipher.decryptor()
        
        # 복호화 수행
        decrypted_data = decryptor.update(encrypted_data) + decryptor.finalize()
        
        print(f"복호화 성공! 복호화된 데이터 크기: {len(decrypted_data)} 바이트")
        return decrypted_data
        
    except Exception as e:
        print(f"복호화 실패: {e}")
        print("가능한 원인:")
        print("1. 잘못된 키 또는 IV")
        print("2. 파일 손상")
        print("3. 올바르지 않은 파일 형식")
        raise

def save_decrypted_data(decrypted_data, output_path):
    """복호화된 데이터를 파일로 저장"""
    with open(output_path, 'wb') as f:
        f.write(decrypted_data)
    print(f"복호화된 데이터가 저장되었습니다: {output_path}")

def analyze_audio_data(data):
    """복호화된 오디오 데이터 분석"""
    print(f"\n=== 오디오 데이터 분석 ===")
    print(f"데이터 크기: {len(data)} 바이트")
    
    if len(data) % 2 == 0:
        # 16비트 샘플 수 계산
        num_samples = len(data) // 2
        print(f"16비트 샘플 수: {num_samples}")
        
        # 16kHz 기준 재생 시간 계산
        duration_seconds = num_samples / 16000
        print(f"재생 시간 (16kHz 기준): {duration_seconds:.2f}초")
        
        # 샘플 값 범위 확인 (처음 몇 개만)
        if len(data) >= 10:
            samples = []
            for i in range(0, min(10, len(data) - 1), 2):
                sample = struct.unpack('<h', data[i:i+2])[0]  # little-endian 16비트
                samples.append(sample)
            print(f"처음 5개 샘플 값: {samples}")
    else:
        print("홀수 바이트 수 - 16비트 샘플이 아닐 수 있습니다.")

def create_wav_header(data_size, sample_rate=16000, channels=1, bits_per_sample=16):
    """WAV 헤더 생성"""
    header = bytearray()
    
    # RIFF 헤더
    header.extend(b'RIFF')
    header.extend(struct.pack('<I', data_size + 36))  # 파일 크기 - 8
    header.extend(b'WAVE')
    
    # fmt 청크
    header.extend(b'fmt ')
    header.extend(struct.pack('<I', 16))  # fmt 청크 크기
    header.extend(struct.pack('<H', 1))   # PCM 포맷
    header.extend(struct.pack('<H', channels))
    header.extend(struct.pack('<I', sample_rate))
    header.extend(struct.pack('<I', sample_rate * channels * bits_per_sample // 8))  # 바이트/초
    header.extend(struct.pack('<H', channels * bits_per_sample // 8))  # 블록 정렬
    header.extend(struct.pack('<H', bits_per_sample))
    
    # data 청크
    header.extend(b'data')
    header.extend(struct.pack('<I', data_size))
    
    return header

def save_as_wav(decrypted_data, output_path):
    """복호화된 데이터를 WAV 파일로 저장"""
    wav_header = create_wav_header(len(decrypted_data))
    
    with open(output_path, 'wb') as f:
        f.write(wav_header)
        f.write(decrypted_data)
    
    print(f"WAV 파일로 저장되었습니다: {output_path}")

def main():
    if len(sys.argv) != 2:
        print("사용법: python aes256_decrypt.py <encrypted_file>")
        print("예시: python aes256_decrypt.py session_20250915_143020.enc")
        sys.exit(1)
    
    encrypted_file = sys.argv[1]
    
    try:
        print(f"암호화된 파일 복호화 중: {encrypted_file}")
        print(f"사용된 키 (UTF-8): {KEY_UTF8}")
        print("=" * 50)
        
        # 복호화 수행
        decrypted_data = decrypt_aes256_cbc(encrypted_file)
        
        # 복호화된 데이터 분석
        analyze_audio_data(decrypted_data)
        
        # 출력 파일명 생성
        base_name = os.path.splitext(encrypted_file)[0]
        raw_output = f"{base_name}_decrypted.raw"
        wav_output = f"{base_name}_decrypted.wav"
        
        # Raw 데이터로 저장
        save_decrypted_data(decrypted_data, raw_output)
        
        # WAV 파일로 저장 (16kHz 모노 16비트 가정)
        save_as_wav(decrypted_data, wav_output)
        
        print("\n복호화 완료!")
        print(f"Raw 파일: {raw_output}")
        print(f"WAV 파일: {wav_output}")
        
    except Exception as e:
        print(f"오류 발생: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()