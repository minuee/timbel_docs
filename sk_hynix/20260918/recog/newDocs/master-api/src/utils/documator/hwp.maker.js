import os from 'os';
import fs from 'fs';
import tmp from 'tmp';
import path from 'path';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';

// __dirname 대체
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// 임시 파일 자동 삭제 설정
tmp.setGracefulCleanup();

/**
 * HWP 문서 생성기 클래스
 */
class HwpMaker {
	/**
	 * 생성자
	 * @param {string} koreanFont 한글 폰트 이름 (기본값: '맑은 고딕')
	 */
	constructor(koreanFont = '맑은 고딕') {
		this.koreanFont = koreanFont;

		// JAR 파일 경로 (동적으로 hwp-generator로 시작하는 파일 검색)
		const jarDir = path.resolve(__dirname);
		const jarFiles = fs.readdirSync(jarDir).filter(file => file.match(/^hwp-generator.*\.jar$/));
		if (jarFiles.length === 0) {
			throw new Error(`JAR 파일을 찾을 수 없습니다. (패턴: hwp-generator*.jar)`);
		}
		// 가장 마지막(최신) 파일 사용
		this.jarPath = path.resolve(jarDir, jarFiles[jarFiles.length - 1]);

		// 임시 디렉토리 - OS의 임시 디렉토리 아래 hwp-temp 폴더 (nodemon 감시 대상 외부)
		this.tempDir = path.join(os.tmpdir(), 'hwp-temp');

		// 임시 디렉토리가 없으면 생성
		if (!fs.existsSync(this.tempDir)) {
			fs.mkdirSync(this.tempDir, { recursive: true });
		}

		console.log('JAR 경로:', this.jarPath);
		console.log('임시 디렉터리:', this.tempDir);
	}

	/**
	 * 문서 제목 설정
	 * @param {string} title 문서 제목
	 */
	setTitle(title) {
		this.title = title;
	}

	/**
	 * Java 프로세스 실행
	 * @param {Array} args 명령줄 인수
	 * @param {number} timeout 타임아웃(ms)
	 * @returns {Promise<{stdout: string, stderr: string}>} 실행 결과
	 */
	executeJavaProcess(args, timeout = 30000) {
		return new Promise((resolve, reject) => {
			// 타임아웃 처리
			let timeoutId = null;
			if (timeout > 0) {
				timeoutId = setTimeout(() => {
					if (process) {
						// Windows에서는 taskkill, Unix에서는 kill로 프로세스 종료
						try {
							process.kill();
						} catch (e) {
							console.error('프로세스 강제 종료 실패:', e.message);
						}
						reject(new Error('프로세스 실행 시간 초과'));
					}
				}, timeout);
			}

			let stdout = '';
			let stderr = '';

			// 자바 프로세스 생성
			const process = spawn('java', args, {
				windowsHide: true, // Windows에서 창 숨김
			});

			// 출력 수집
			process.stdout.on('data', data => {
				stdout += data.toString();
			});

			process.stderr.on('data', data => {
				stderr += data.toString();
			});

			// 프로세스 종료 처리
			process.on('close', code => {
				if (timeoutId) clearTimeout(timeoutId);

				if (code === 0) {
					resolve({ stdout, stderr });
				} else {
					const error = new Error(`프로세스가 종료 코드 ${code}로 종료됨`);
					error.code = code;
					error.stdout = stdout;
					error.stderr = stderr;
					reject(error);
				}
			});

			// 오류 처리
			process.on('error', err => {
				if (timeoutId) clearTimeout(timeoutId);
				reject(err);
			});
		});
	}

	/**
	 * HWP 문서 생성
	 * @param {Array} textObjects 텍스트 객체 배열
	 * @param {string} title 문서 제목 (선택적)
	 * @returns {Promise<Buffer>} 생성된 HWP 파일 버퍼
	 */
	async createHwp(textObjects, title) {
		// 임시 파일들 (tmp 패키지 사용하여 생성)
		let tmpJsonFile = null;
		let tmpHwpFile = null;

		textObjects = [
			{
				text: `${title}\n`,
				styles: { size: 18, bold: true, alignment: 'center', bottomSpace: 30 },
			},
			{ text: '\n' },
			...textObjects,
		];

		try {
			// 임시 HWP 파일 생성
			tmpHwpFile = tmp.fileSync({
				prefix: 'hwp-',
				postfix: '.hwp',
				dir: this.tempDir,
				keep: true, // 수동으로 삭제하기 위해 유지
			});

			// 임시 JSON 파일 생성
			tmpJsonFile = tmp.fileSync({
				prefix: 'json-',
				postfix: '.json',
				dir: this.tempDir,
				keep: true, // 수동으로 삭제하기 위해 유지
			});

			const outputFile = tmpHwpFile.name;
			const tempJsonFile = tmpJsonFile.name;

			// 빈 배열이나 null/undefined 확인
			if (!textObjects || !Array.isArray(textObjects) || textObjects.length === 0) {
				console.warn('경고: 텍스트 객체가 비어있습니다. 기본 내용을 생성합니다.');
				textObjects = [{ text: '기본 문서 내용', styles: { fontSize: 10 } }];
			}

			// JAR 파일 존재 확인
			if (!fs.existsSync(this.jarPath)) {
				throw new Error(`JAR 파일을 찾을 수 없습니다: ${this.jarPath}`);
			}

			// 임시 JSON 파일에 내용 쓰기
			fs.writeFileSync(tempJsonFile, JSON.stringify(textObjects, null, 2), 'utf8');
			console.log(`JSON 파일 생성됨: ${tempJsonFile}`);

			console.log('HWP 파일 생성 시작...');

			// Java 프로세스 실행 (child_process 사용)
			try {
				console.log('자바 프로세스 실행 시작...');

				// 실행 명령 - 두 번째 인자로 JSON 파일 경로 전달
				const javaArgs = ['-jar', this.jarPath, outputFile, tempJsonFile];
				console.log('실행 명령:', 'java', ...javaArgs);

				// 프로세스 실행 및 결과 처리
				const result = await this.executeJavaProcess(javaArgs, 30000);

				console.log('자바 프로세스 실행 완료');

				// 출력 로깅
				if (result.stdout) console.log('명령어 출력:', result.stdout);
				if (result.stderr && result.stderr.trim() !== '') console.log('표준 오류:', result.stderr);
			} catch (execError) {
				// 오류 상세 처리
				console.error('자바 프로세스 실행 중 오류:', execError.message);

				if (execError.message.includes('시간 초과')) {
					console.error('HWP 생성 시간 초과 (30초)');
					throw new Error('HWP 생성 시간 초과 (30초)');
				}

				if (execError.stderr) console.error('표준 오류:', execError.stderr);
				throw new Error(`Java 프로세스 오류: ${execError.message}`);
			}

			// 파일 확인 (약간 지연 - 파일 시스템 동기화를 위해)
			await new Promise(resolve => setTimeout(resolve, 100));

			if (!fs.existsSync(outputFile)) {
				throw new Error('HWP 파일이 생성되지 않았습니다.');
			}

			// 파일 정보 및 버퍼 읽기
			const stats = fs.statSync(outputFile);
			console.log(`HWP 파일 생성됨: ${outputFile} (${stats.size} bytes)`);

			// 파일 내용을 버퍼로 읽기
			const buffer = fs.readFileSync(outputFile);

			return buffer;
		} catch (error) {
			// 오류 처리 및 타입별 메시지
			console.error('HWP 생성 중 예외 발생:', error.message);
			throw new Error(`HWP 변환 오류: ${error.message}`);
		} finally {
			// 임시 파일 삭제
			if (tmpJsonFile) {
				try {
					tmpJsonFile.removeCallback();
					console.log('JSON 임시 파일 삭제됨');
				} catch (e) {
					console.log(`JSON 임시 파일 삭제 실패: ${e.message}`);
				}
			}

			if (tmpHwpFile) {
				try {
					tmpHwpFile.removeCallback();
					console.log('HWP 임시 파일 삭제됨');
				} catch (e) {
					console.log(`HWP 임시 파일 삭제 실패: ${e.message}`);
				}
			}

			console.log('임시 파일 정리 완료');
		}
	}
}

export default HwpMaker;
