import argparse
import asyncio
import json
import logging
import os
import wave

import numpy as np
import websockets

# 로거 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 상수
SAMPLE_WIDTH = 2  # 16비트 샘플
DEFAULT_SAMPLE_RATE = 8000
CHUNK_SIZE = 4000  # 전송할 청크 크기 (bytes)

# 전송/수신 및 WebSocket 동작 관련 상수
SEND_PACING_SEC = 0.24  # 청크 전송 사이 대기 시간(초). 0이면 페이싱 없음
RECV_TIMEOUT_SEC = 30.0  # 수신 대기 타임아웃(초)
WS_PING_INTERVAL_SEC = 30  # WebSocket 핑 간격(초)
WS_PING_TIMEOUT_SEC = 10  # WebSocket 핑 타임아웃(초)
WS_MAX_SIZE: int | None = None  # 수신 메시지 최대 크기(None은 제한 없음)
WS_MAX_QUEUE = 32  # 라이브러리 내부 수신 큐 크기
EOS_SIGNAL = "EOS"  # 서버가 요구하는 EOS 신호

# HAIV STT API 설정 (원본 코드에서 가져옴)
# BASE   = "wss://haiv.timbel.net:40002"
# PRJ_ID = "2e77c961-f709-400a-8c3e-0eeb73604698"

#BASE = "wss://dev-ecp-haiv.langsa.ai"
#PRJ_ID = "4a7b5307-e3c3-4d40-bb5d-3e0c59120497"
BASE = "ws://124.194.32.36:17778"
PRJ_ID = "f46d3019-129b-48c2-9a8f-67dd29b80b42"

def get_stt_url(
    model_name: str = "KOREAN_ONLINE_8K",
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    call_id: str | None = None,
    speaker_div: str | None = None,
    agent_id: str | None = None,
    tenant_id: str | None = None,
    company_id: str | None = None,
    customer_num: str | None = None,
    extension_num: str | None = None,
    in_outbound: str | None = None,
    skill_id: str | None = None,
    ucid: str | None = None,
) -> str:
    """STT 웹소켓 URL을 생성하는 함수

    call_id: 콜 식별자(선택)
    speaker_div: 화자 구분(선택) - 송신(상담원): T1, 수신(고객): R1
    company_id: 회사 식별자(선택)
    customer_num: 고객 번호(선택)
    extension_num: 내선 번호(선택)
    in_outbound: 인바운드/아웃바운드 구분(선택)
    skill_id: 스킬 ID(선택)
    ucid: UCID(선택)
    """
    base = (
        f"{BASE}/client/ws/speech?"
        "single=false"
        f"&model={model_name}"
        f"&project={PRJ_ID}"
        "&content-type=audio%2Fx-raw%2C%20layout%3D%28string%29interleaved%2C%20"
        f"rate%3D%28int%29{sample_rate}%2C%20format%3D%28string%29S16LE%2C%20"
        "channels%3D%28int%291"
    )
    if call_id:
        base += f"&call-id={call_id}"
    if speaker_div:
        base += f"&speaker-div={speaker_div}"
    if agent_id:
        base += f"&agent-id={agent_id}"
    if tenant_id:
        base += f"&tenant-id={tenant_id}"
    if company_id:
        base += f"&company-id={company_id}"
    if customer_num:
        base += f"&customer-num={customer_num}"
    if extension_num:
        base += f"&extension-num={extension_num}"
    if in_outbound:
        base += f"&in-outbound={in_outbound}"
    if skill_id:
        base += f"&skill-id={skill_id}"
    if ucid:
        base += f"&ucid={ucid}"
    return base


class WAVFileSTTSender:
    """WAV 파일을 읽어서 STT 서버로 전송하고 결과를 받는 클래스"""

    def __init__(
        self,
        model_name: str = "KOREAN_ONLINE_8K",
        target_sample_rate: int = DEFAULT_SAMPLE_RATE,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        call_id: str | None = None,
        speaker_div: str | None = None,
        agent_id: str | None = None,
        tenant_id: str | None = None,
        company_id: str | None = None,
        customer_num: str | None = None,
        extension_num: str | None = None,
        in_outbound: str | None = None,
        skill_id: str | None = None,
        ucid: str | None = None,
    ):
        self.model_name = model_name
        self.target_sample_rate = target_sample_rate
        self.call_id = call_id
        self.speaker_div = speaker_div
        self.agent_id = agent_id
        self.websocket_url = get_stt_url(
            model_name,
            target_sample_rate,
            call_id,
            speaker_div,
            agent_id,
            tenant_id,
            company_id,
            customer_num,
            extension_num,
            in_outbound,
            skill_id,
            ucid,
        )
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # 동작 파라미터 설정
        self.send_pacing_sec = SEND_PACING_SEC
        self.recv_timeout_sec = RECV_TIMEOUT_SEC
        self.ping_interval = WS_PING_INTERVAL_SEC
        self.ping_timeout = WS_PING_TIMEOUT_SEC
        self.ws_max_size = WS_MAX_SIZE
        self.ws_max_queue = WS_MAX_QUEUE

        logger.info(f"STT URL: {self.websocket_url}")

    def read_wav_file(self, wav_path: str) -> tuple[bytes, int, int]:
        """WAV 파일을 읽어서 PCM 데이터를 반환"""
        if not os.path.exists(wav_path):
            raise FileNotFoundError(f"WAV file not found: {wav_path}")

        try:
            with wave.open(wav_path, "rb") as wav_file:
                # WAV 파일 정보
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                frames = wav_file.getnframes()

                logger.info(f"WAV 파일 정보: {channels}ch, {sample_width * 8}bit, {sample_rate}Hz, {frames} frames")

                # 스테레오인 경우 모노로 변환 필요성 체크
                if channels != 1:
                    logger.warning(f"다중 채널 오디오 ({channels}ch) 감지됨. 모노로 변환이 필요할 수 있습니다.")

                # 16비트가 아닌 경우 경고
                if sample_width != 2:
                    logger.warning(f"16비트가 아닌 샘플 폭 ({sample_width * 8}bit) 감지됨.")

                # PCM 데이터 읽기
                pcm_data = wav_file.readframes(frames)

                return pcm_data, sample_rate, channels

        except Exception as e:
            raise Exception(f"WAV 파일 읽기 실패: {e!s}") from e

    def preprocess_audio(self, pcm_data: bytes, source_sample_rate: int, channels: int) -> bytes:
        """오디오 전처리 - 리샘플링 및 모노 변환"""
        try:
            # 바이트 데이터를 numpy 배열로 변환
            audio_array = np.frombuffer(pcm_data, dtype=np.int16)

            # 스테레오를 모노로 변환
            if channels == 2:
                # 스테레오 데이터를 L, R 채널로 분리하고 평균내기
                audio_array = audio_array.reshape(-1, 2)
                audio_array = np.mean(audio_array, axis=1).astype(np.int16)
                logger.info("스테레오를 모노로 변환 완료")

            # 리샘플링 (간단한 다운샘플링)
            if source_sample_rate != self.target_sample_rate:
                # 다운샘플링 비율 계산
                downsample_ratio = source_sample_rate // self.target_sample_rate
                if downsample_ratio > 1:
                    # 간단한 데시메이션 (매 N번째 샘플만 선택)
                    audio_array = audio_array[::downsample_ratio]
                    logger.info(
                        f"리샘플링 완료: {source_sample_rate}Hz -> {self.target_sample_rate}Hz (ratio: {downsample_ratio})"
                    )
                else:
                    logger.warning(f"업샘플링은 지원되지 않습니다. 원본 샘플레이트 사용: {source_sample_rate}Hz")

            # numpy 배열을 다시 바이트로 변환
            return audio_array.astype(np.int16).tobytes()

        except Exception as e:
            logger.error(f"오디오 전처리 실패: {e}")
            return pcm_data  # 실패시 원본 반환

    def split_audio_chunks(self, pcm_data: bytes, chunk_size: int = CHUNK_SIZE) -> list[bytes]:
        """PCM 데이터를 청크로 분할"""
        chunks = []
        for i in range(0, len(pcm_data), chunk_size):
            chunk = pcm_data[i : i + chunk_size]
            chunks.append(chunk)

        # logger.info(f"오디오를 {len(chunks)}개 청크로 분할 (청크 크기: {chunk_size} bytes)")
        return chunks

    async def send_wav_file(self, wav_path: str, send_chunks: bool = True) -> list[str]:
        """WAV 파일을 STT 서버로 전송하고 결과를 받음"""
        # WAV 파일 읽기
        pcm_data, sample_rate, channels = self.read_wav_file(wav_path)

        # 오디오 전처리
        processed_audio = self.preprocess_audio(pcm_data, sample_rate, channels)

        # 전송할 데이터 준비
        if send_chunks:
            audio_chunks = self.split_audio_chunks(processed_audio)
        else:
            audio_chunks = [processed_audio]  # 전체를 한 번에 전송

        # STT 서버로 전송
        return await self._send_to_stt_server(audio_chunks)

    async def _send_to_stt_server(self, audio_chunks: list[bytes]) -> list[str]:
        """오디오 청크들을 STT 서버로 전송하고 결과를 받음"""
        results: list[str] = []
        websocket = None

        for attempt in range(self.max_retries):
            try:
                logger.info(f"STT 서버 연결 시도 {attempt + 1}/{self.max_retries}")

                # WebSocket 연결
                websocket = await websockets.connect(
                    self.websocket_url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    max_size=self.ws_max_size,
                    max_queue=self.ws_max_queue,
                )

                logger.info("STT 서버 연결 성공")

                stop_sending = asyncio.Event()
                session_id: str | None = None
                final_results: list[str] = []

                async def send_audio_chunks() -> int:
                    total_sent = 0
                    for i, chunk in enumerate(audio_chunks):
                        if stop_sending.is_set():
                            logger.info("송신 중단 신호 감지, 전송 루프 종료")
                            break
                        await websocket.send(chunk)
                        total_sent += len(chunk)
                        # logger.info(f"청크 {i + 1}/{len(audio_chunks)} 전송 완료 ({len(chunk)} bytes)")

                        if self.send_pacing_sec > 0:
                            await asyncio.sleep(self.send_pacing_sec)
                    # EOS는 정상 송신 완료 시에만 전송
                    if not stop_sending.is_set():
                        await websocket.send(EOS_SIGNAL)
                        logger.info(f"총 {total_sent} bytes 전송 완료, EOS 신호 전송")
                    return total_sent

                async def receive_messages() -> None:
                    nonlocal session_id, final_results
                    while True:
                        try:
                            response = await asyncio.wait_for(websocket.recv(), timeout=self.recv_timeout_sec)
                        except TimeoutError:
                            logger.info("응답 타임아웃 - 계속 대기")
                            continue
                        except websockets.exceptions.ConnectionClosed as e:
                            try:
                                code = e.code
                                reason = e.reason
                            except Exception:
                                code = None
                                reason = ""
                            logger.info(f"연결 종료(code={code}, reason={reason})")
                            stop_sending.set()
                            break

                        # Progress 텍스트 처리
                        if isinstance(response, (bytes, bytearray)):
                            try:
                                response = response.decode("utf-8", errors="ignore")
                            except Exception:
                                pass
                        if isinstance(response, str) and response.startswith("Progress:"):
                            try:
                                progress = float(response.split(":")[1])
                                logger.info(f"처리 진행률: {progress}%")
                            except Exception:
                                logger.info(f"진행률 파싱 실패: {response}")
                            continue

                        # JSON 파싱
                        try:
                            msg = json.loads(response)
                        except (json.JSONDecodeError, TypeError):
                            logger.warning(f"Non-JSON 메시지 수신: {response}")
                            continue

                        # 세션 ID 추출
                        if "sessionId" in msg and session_id is None:
                            session_id = msg["sessionId"]
                            logger.info(f"세션 ID: {session_id}")

                        # 서버 오류/제어 신호 처리
                        if "error" in msg:
                            logger.error(f"서버 오류: {msg.get('error')}")
                            stop_sending.set()
                            break
                        if msg.get("status") in {"abort", "aborted", "rate_limited"}:
                            logger.warning(f"서버 제어 신호 수신: {msg.get('status')}")
                            stop_sending.set()
                            break

                        # STT 결과 처리
                        if "result" in msg:
                            result_obj = msg["result"]
                            hypotheses = result_obj.get("hypotheses") or []
                            is_final = result_obj.get("final", False)
                            if hypotheses:
                                hyp = hypotheses[0]
                                transcript = hyp.get("transcript", "")
                                if transcript:
                                    logger.info(f"STT 결과: '{transcript}' (final: {is_final})")
                                    if is_final:
                                        final_results.append(transcript)
                    # 수신 루프 종료
                    return

                # 송신/수신 동시 수행: 항상 수신 종료(서버 Close)까지 대기
                send_task = asyncio.create_task(send_audio_chunks())
                await receive_messages()

                # 수신 종료 → 송신 중단 지시 및 정리
                stop_sending.set()
                if not send_task.done():
                    try:
                        await asyncio.wait_for(send_task, timeout=5.0)
                    except TimeoutError:
                        send_task.cancel()
                        await asyncio.gather(send_task, return_exceptions=True)

                if final_results:
                    results = final_results
                    logger.info(f"최종 결과 {len(results)}개 수신")
                    break
                else:
                    logger.warning("STT 결과를 받지 못함")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay)
                        continue

            except Exception as e:
                logger.error(f"시도 {attempt + 1} 실패: {str(e)}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    raise Exception(f"모든 재시도 실패: {e!s}") from e

            finally:
                if websocket:
                    try:
                        await websocket.close()
                    except Exception:
                        pass

        return results


async def main():
    """메인 함수 - 사용 예제"""
    # 인자 파싱 및 WAV 파일 경로 설정
    parser = argparse.ArgumentParser(description="WAV 파일을 STT 서버로 전송하여 텍스트를 받습니다.")
    parser.add_argument("file", nargs="?", help="STT 처리할 WAV 파일 경로")
    parser.add_argument("--call-id", dest="call_id", help="콜 식별자(call-id)")
    parser.add_argument(
        "--speaker", dest="speaker", choices=["T1", "R1"], help="화자 구분: 상담사(송신) T1 / 고객(수신) R1"
    )
    parser.add_argument("--agent-id", dest="agent_id", help="에이전트 식별자(agent-id)")
    parser.add_argument("--tenant-id", dest="tenant_id", help="테넌트 식별자(tenant-id)")
    parser.add_argument("--company-id", dest="company_id", help="회사 식별자(company-id)")
    parser.add_argument("--customer-num", dest="customer_num", help="고객 번호(customer-num)")
    parser.add_argument("--extension-num", dest="extension_num", help="내선 번호(extension-num)")
    parser.add_argument("--in-outbound", dest="in_outbound", help="인바운드/아웃바운드 구분(in-outbound)")
    parser.add_argument("--skill-id", dest="skill_id", help="스킬 ID(skill-id)")
    parser.add_argument("--ucid", dest="ucid", help="UCID")
    args = parser.parse_args()

    if args.file:
        wav_file_path = args.file
    else:
        return

    try:
        # STT 전송기 생성
        stt_sender = WAVFileSTTSender(
#            model_name="KOREAN_ONLINE_8K",
            model_name="KOREAN_ONLINE_8K_NASR",
            target_sample_rate=DEFAULT_SAMPLE_RATE,
            max_retries=3,
            retry_delay=1.0,
            call_id=args.call_id,
            speaker_div=args.speaker,
            agent_id=args.agent_id,
            tenant_id=args.tenant_id,
            company_id=args.company_id,
            customer_num=args.customer_num,
            extension_num=args.extension_num,
            in_outbound=args.in_outbound,
            skill_id=args.skill_id,
            ucid=args.ucid,
        )

        use_chunks = True

        logger.info(f"WAV 파일 STT 처리 시작: {wav_file_path}")

        # WAV 파일 전송 및 STT 처리
        results = await stt_sender.send_wav_file(wav_file_path, send_chunks=use_chunks)

        # 결과 출력
        if results:
            print("\n" + "=" * 50)
            print("STT 처리 결과:")
            print("=" * 50)
            for i, result in enumerate(results, 1):
                print(f"{i}. {result}")

            # 전체 결과 합치기
            if len(results) > 1:
                combined_result = " ".join(results)
                print(f"\n통합 결과: {combined_result}")
        else:
            print("STT 처리 결과가 없습니다.")

    except FileNotFoundError as e:
        logger.error(f"파일을 찾을 수 없습니다: {e}")
    except Exception as e:
        logger.error(f"STT 처리 중 오류 발생: {e}")


if __name__ == "__main__":
    # 비동기 메인 함수 실행
    asyncio.run(main())
