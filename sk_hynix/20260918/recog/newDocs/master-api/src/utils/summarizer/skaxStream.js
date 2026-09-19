import { StateGraph } from "@langchain/langgraph";
import { getCompanyHeader } from './skaxCustomProcess.js';

const TAG = '[summarizer/skax-stream]';

const graphState = {
    uid: {
        value: (x, y) => y,
        default: () => "",
    },
    mid: {
        value: (x, y) => y,
        default: () => "",
    },
    company: {
        value: (x, y) => y,
        default: () => null,
    },
    ticketId: {
        value: (x, y) => y,
        default: () => "",
    },
    progress: {
        value: (x, y) => y,
        default: () => 0,
    },
    final_minutes: {
        value: (x, y) => y,
        default: () => "",
    },
    error: {
        value: (x, y) => y,
        default: () => null,
    },
};

async function* callSummaryApiNode(state) {
    log.i(TAG, `[${state.ticketId}] 요약 API 스트리밍 호출 노드 시작`);
    
    try {
        // 상태(state) 객체에서 uid와 mid를 가져와 API 요청 본문을 만듭니다.
        const requestBody = {
            uid: state.uid,
            mid: state.mid,
        };

        // 회사 헤더 생성
        const companyHeaders = getCompanyHeader(state.company, state.ticketId);
        
        // API URL 설정 (스트리밍 엔드포인트)
        const apiUrl = process.env.SKAX_STREAM_API_URL || 'http://localhost:28080/summary/stream';
        
        log.i(TAG, `[${state.ticketId}] API URL: ${apiUrl}`);
        log.i(TAG, `[${state.ticketId}] Request Body: ${JSON.stringify(requestBody)}`);

        // fetch를 사용한 API 호출 로직 (기존 RemoteRunnable의 역할)
        const response = await fetch(apiUrl, {
            method: 'POST',
            headers: {
                "accept": "application/json",
                "aip-user": "aiplatform3/agenttest",
                "Authorization": "EMPTY",
                "Content-Type": "application/json",
                ...companyHeaders,
            },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const errorText = await response.text();
            log.e(TAG, `[${state.ticketId}] HTTP Error: ${response.status} - ${errorText}`);
            throw new Error(`HTTP Error: ${response.status} - ${errorText}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let currentProgress = 0;

        // 스트림 처리
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            // 서버가 줄바꿈으로 JSON 객체를 구분한다고 가정합니다.
            const lines = chunk.split('\n').filter(line => line.trim());

            for (const line of lines) {
                try {
                    const data = JSON.parse(line);

                    // 'progress' 또는 'progress_step'이 오면 progress 상태를 업데이트하여 yield로 내보냅니다.
                    if (data.progress !== undefined) {
                        currentProgress = data.progress;
                        log.i(TAG, `[${state.ticketId}] Progress: ${currentProgress}%`);
                        yield { progress: currentProgress };
                    } else if (data.progress_step) {
                        currentProgress += data.progress_step;
                        log.i(TAG, `[${state.ticketId}] Progress: ${currentProgress}%`);
                        yield { progress: currentProgress };
                    }

                    // 'final_minutes' 또는 'output'이 오면 final_minutes 상태를 업데이트하여 yield로 내보냅니다.
                    if (data.final_minutes) {
                        log.i(TAG, `[${state.ticketId}] Final minutes received`);
                        yield { final_minutes: data.final_minutes };
                    } else if (data.output && data.output.final_minutes) {
                        log.i(TAG, `[${state.ticketId}] Final minutes received from output`);
                        yield { final_minutes: data.output.final_minutes };
                    }

                    // 에러가 있는 경우 처리
                    if (data.error) {
                        log.e(TAG, `[${state.ticketId}] API Error: ${data.error}`);
                        yield { error: data.error };
                        throw new Error(data.error);
                    }
                } catch (parseError) {
                    // 파싱 에러는 로깅만 하고 계속 진행
                    log.w(TAG, `[${state.ticketId}] JSON parse error: ${parseError.message} - Line: ${line}`);
                }
            }
        }
        
        log.i(TAG, `[${state.ticketId}] 요약 API 스트리밍 호출 노드 종료`);
        
    } catch (error) {
        log.e(TAG, `[${state.ticketId}] API 호출 중 오류 발생: ${error.message}`);
        yield { error: error.message };
        throw error;
    }
}


// 3. 워크플로우 그래프를 정의하고 컴파일합니다.
function createSummaryWorkflow() {
    const workflow = new StateGraph({ channels: graphState });

    // 노드를 추가하고, 시작점과 끝점을 설정합니다. (단일 노드 워크플로우)
    workflow.addNode("summarizer", callSummaryApiNode);
    workflow.setEntryPoint("summarizer");
    workflow.addFinishPoint("summarizer");

    return workflow.compile();
}

// 4. 스트리밍 요약을 실행하는 메인 함수
export async function runSkaxStreamingSummary({ uid, mid, company, ticketId, onProgress, onComplete, onError }) {
    try {
        const app = createSummaryWorkflow();
        
        // 그래프 실행 시 초기 상태값을 전달합니다.
        const inputs = {
            uid,
            mid,
            company,
            ticketId,
        };

        log.i(TAG, `[${ticketId}] 스트리밍 요약 시작 - uid: ${uid}, mid: ${mid}`);

        // streamMode: 'updates'는 상태의 변경분만 실시간으로 받아보게 해줍니다.
        for await (const update of app.stream(inputs, { streamMode: "updates" })) {
            // 'summarizer' 노드에서 발생한 업데이트만 처리합니다.
            if (update.summarizer) {
                const { progress, final_minutes, error } = update.summarizer;
                
                if (error) {
                    log.e(TAG, `[${ticketId}] 스트리밍 중 오류 발생: ${error}`);
                    if (onError) {
                        onError(new Error(error));
                    }
                    return;
                }
                
                if (progress !== undefined) {
                    log.i(TAG, `[${ticketId}] Progress: ${progress}%`);
                    if (onProgress) {
                        onProgress(progress);
                    }
                }
                
                if (final_minutes !== undefined) {
                    log.i(TAG, `[${ticketId}] 요약 완료`);
                    if (onComplete) {
                        onComplete(final_minutes);
                    }
                    return;
                }
            }
        }
        
    } catch (error) {
        log.e(TAG, `[${ticketId}] 스트리밍 요약 실행 중 오류: ${error.message}`);
        if (onError) {
            onError(error);
        }
        throw error;
    }
}

// 기존 skaxCustomProcess와 호환되는 클래스 형태의 래퍼
class SkaxStreamingProcess {
    constructor({ uid, mid, company, ticketId }) {
        this.uid = uid;
        this.mid = mid;
        this.company = company;
        this.ticketId = ticketId;
    }

    async runner() {
        return new Promise((resolve, reject) => {
            let finalResult = null;
            
            runSkaxStreamingSummary({
                uid: this.uid,
                mid: this.mid,
                company: this.company,
                ticketId: this.ticketId,
                onProgress: (progress) => {
                    // 진행률은 로깅만 하고 반환하지 않음 (기존 runner와 호환성 유지)
                    log.i(TAG, `[${this.ticketId}] 진행률: ${progress}%`);
                },
                onComplete: (final_minutes) => {
                    finalResult = final_minutes;
                    resolve({
                        note: final_minutes,
                        title: '스트리밍 요약 완료',
                        aiResult: {},
                        summaryTime: [],
                        totalToken: 0
                    });
                },
                onError: (error) => {
                    reject(error);
                }
            });
        });
    }
}

export default SkaxStreamingProcess;
