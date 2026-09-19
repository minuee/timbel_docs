import fs from 'fs';
import path from 'path';
import ffmpeg from 'fluent-ffmpeg';
import { PassThrough } from 'stream';
import { HttpError } from '../../handlers/error.handler.js';

class AudioUtil {
	toFlac({ buffer }, outputPath) {
		return new Promise((resolve, reject) => {
			const inputStream = new PassThrough();
			inputStream.end(buffer);

			const startTime = Date.now();

			ffmpeg(inputStream)
				.inputFormat('wav')
				.outputOptions(['-f s16le', '-ar 16000', '-ac 1', '-map_metadata 0'])
				.toFormat('flac')
				.save(outputPath)
				.on('end', () => {
					const endTime = Date.now();
					const duration = (endTime - startTime) / 1000;
					log.i(`[toFlac] Wav Buffer To Flac 변환 소요 시간 ${duration.toFixed(2)} 초`);
					resolve();
				})
				.on('error', err => reject(err));
		});
	}

	async replaceFileWithFlac(file) {
		const timestamp = Date.now();
		const randomStr = Math.random().toString(36).substring(2, 15);
		const uniqueFolder = `convert_${timestamp}_${randomStr}`;

		const fileName = file.originalname.replace('.wav', '.flac');
		const outputDir = path.join('./tmp/', uniqueFolder);
		const outputPath = path.join(outputDir, fileName);

		log.i('[AudioUtil : replaceFileWithFlac] outputPath : ', outputPath);
		try {
			await fs.promises.mkdir(outputDir, { recursive: true });

			await this.toFlac(file, outputPath);

			const flacBuffer = fs.readFileSync(outputPath);

			const flacSizeBytes = fs.statSync(outputPath).size;
			const flacSizeMB = (flacSizeBytes / (1024 * 1024)).toFixed(2);
			log.i(`[replaceFileWithFlac] 변환 후 파일 크기: ${flacSizeMB} MB`);

			file.path = outputPath;
			file.originalname = fileName;
			file.mimetype = 'audio/flac';
			file.size = flacSizeBytes;
			file.buffer = flacBuffer;

			fs.rm(outputDir, { recursive: true, force: true }, err => {
				if (err) {
					log.e(`[replaceFileWithFlac] 임시 폴더 제거 실패: ${outputDir}`, err);
				} else {
					log.i(`[replaceFileWithFlac] 임시 폴더 제거: ${outputDir}`);
				}
			});

			return file;
		} catch (err) {
			fs.rm(outputDir, { recursive: true, force: true }, () => {});
			throw new HttpError(1132, err.message);
		}
	}

	async convertPcmToFlac(inputFile, outputPath, outputFileName) {
		await fs.promises.mkdir(outputPath, { recursive: true });

		const outputFile = path.join(outputPath, `${outputFileName}.flac`);
		const startTime = Date.now();

		await new Promise((resolve, reject) =>
			ffmpeg(inputFile)
				.inputOptions(['-f s16le', '-ar 16000', '-ac 1'])
				.audioCodec('flac')
				.on('end', resolve)
				.on('error', reject)
				.save(outputFile)
		);
		const duration = (Date.now() - startTime) / 1000;
		log.i(`[AudioUtil : convertPcmToFlac] pcm to flac convert time : ${outputFile} / ${duration.toFixed(2)} sec`);
		return outputFile;
	}

	async cleanupTempFiles(tempOutputPath, tempInputPath, functionName = 'normalizeAudioFile') {
		try {
			// 임시 출력 파일 삭제
			if (tempOutputPath && fs.existsSync(tempOutputPath)) {
				await fs.promises.unlink(tempOutputPath);
			}

			// 임시 입력 파일이 있으면 해당 폴더 전체 삭제
			if (tempInputPath && fs.existsSync(tempInputPath)) {
				const tempDir = path.dirname(tempInputPath);
				fs.rm(tempDir, { recursive: true, force: true }, err => {
					if (err) {
						log.e(`[${functionName}] 임시 폴더 제거 실패: ${tempDir}`, err);
					} else {
						log.i(`[${functionName}] 임시 폴더 제거 완료: ${tempDir}`);
					}
				});
			}
		} catch (err) {
			log.e(`[${functionName}] 임시 파일 정리 중 오류 발생: ${err.message}`, err);
		}
	}

	async normalizeAudioFile(tempFilePath) {
		const functionStartTime = Date.now();
		let tempOutputPath = null;

		if (!tempFilePath) {
			throw new HttpError(1132, 'tempFilePath is required');
		}

		if (!fs.existsSync(tempFilePath)) {
			throw new HttpError(1132, `File not found: ${tempFilePath}`);
		}

		try {
			const inputDir = path.dirname(tempFilePath);
			const inputFileName = path.basename(tempFilePath, path.extname(tempFilePath));
			tempOutputPath = path.join(inputDir, `${inputFileName}_normalized.tmp.flac`);

			const startTime = Date.now();
			log.i(`[normalizeAudioFile] 정규화 시작: ${tempFilePath}`);

			await new Promise((resolve, reject) => {
				ffmpeg(tempFilePath)
					.audioFilters('loudnorm=I=-16:TP=-1.5:LRA=11')
					.outputOptions(['-ar 16000', '-sample_fmt s16'])
					.toFormat('flac')
					.save(tempOutputPath)
					.on('end', resolve)
					.on('error', reject);
			});

			const endTime = Date.now();
			const duration = (endTime - startTime) / 1000;
			log.i(`[normalizeAudioFile] 정규화 완료 소요 시간: ${duration.toFixed(2)} 초`);

			await fs.promises.copyFile(tempOutputPath, tempFilePath);

			const normalizedSizeBytes = fs.statSync(tempFilePath).size;
			const normalizedSizeMB = (normalizedSizeBytes / (1024 * 1024)).toFixed(2);

			log.i(`[normalizeAudioFile] 정규화 후 파일 크기: ${normalizedSizeMB} MB`);

			const functionEndTime = Date.now();
			const totalDuration = (functionEndTime - functionStartTime) / 1000;
			log.i(`[normalizeAudioFile] 전체 처리 소요 시간: ${totalDuration.toFixed(2)} 초`);

			return tempFilePath;
		} catch (err) {
			const functionEndTime = Date.now();
			const totalDuration = (functionEndTime - functionStartTime) / 1000;
			log.e(
				`[normalizeAudioFile] 정규화 실패, 원본 파일 유지 (소요 시간: ${totalDuration.toFixed(2)} 초): ${err.message}`,
				err
			);
			return tempFilePath;
		} finally {
			await this.cleanupTempFiles(tempOutputPath, null, 'normalizeAudioFile');
		}
	}
}

export default new AudioUtil();
