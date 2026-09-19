import fs from 'fs';
import tmp from 'tmp';
import path from 'path';
import { Client } from '@timbel-timblo-onpremise/minio-js';
import { pipeline } from 'stream/promises';
import { HttpError } from '../handlers/error.handler.js';
import { redis, secure, generate } from '../utils/index.js';

const { env } = process;
let MinioClient = null;
process.on('storageChanged', () => {
	if (MinioClient) {
		try {
			if (typeof MinioClient.destroy === 'function') {
				MinioClient.destroy();
			} else if (typeof MinioClient.end === 'function') {
				MinioClient.end();
			}
			log.i('[DriveUtil : storageChanged] 이전 MinioClient 정리 완료');
		} catch (err) {
			log.e('[DriveUtil : storageChanged] 이전 클라이언트 정리 중 오류:', err.message);
		}
	}

	MinioClient = new Client({
		endPoint: env.END_POINT || 'timblo-minio',
		port: env.END_POINT_PORT ? Number(env.END_POINT_PORT) : 9000,
		accessKey: env.ACCESS_KEY_ID,
		secretKey: env.SECRET_ACCESS_KEY,
		region: env.REGION || 'ap-northeast-2',
		useSSL: env.USE_SSL === 'true',
	});
});

export default class DriveUtil {
	constructor({ kms, config }) {
		this.kms = kms ?? null;
		this.isMobile = config?.isMobile ?? false;
		return this;
	}

	createPutParams() {
		const { originalname, size, mimetype } = this.file;
		return {
			'Content-Type': mimetype,
			'Content-Length': size,
			originalname: encodeURIComponent(originalname),
		};
	}

	createFileData(key) {
		const { originalname, size, mimetype, inputType, isRecord, folderId = undefined } = this.file;
		return {
			size,
			folderId,
			isRecord,
			inputType,
			apiKey: key,
			mimeType: mimetype,
			title: originalname,
			isMobile: this.isMobile,
		};
	}

	async backUpFile(fullPath) {
		const tempDir = './failedUploadFile';
		const fileName = path.basename(fullPath);
		const tempFilePath = path.join(tempDir, fileName);

		if (!fs.existsSync(tempDir)) {
			fs.mkdirSync(tempDir, { recursive: true });
		}

		await fs.promises.writeFile(tempFilePath, this.file.buffer);
		return tempFilePath;
	}

	async fastLoadFile(path, extension) {
		log.i('[DriveUtil : fastLoadFile] Start');
		await this.getHeadObjectFromCacheOrStorage(path);
		log.i('[DriveUtil : fastLoadFile] head object cache complete');
		const objectParams = this.createGetParams(path);
		log.i('[DriveUtil : fastLoadFile] End');
		return this.getObject(path, objectParams, extension);
	}

	async put(file) {
		this.file = file;
		const key = generate.fileKey();
		const fullPath = `${this.kms}/${key}`;
		const params = this.createPutParams();
		const extension = this.file.originalname.split('.')[1];
		log.i('[DriveUtil : put] FullPath : ', fullPath);

		try {
			const result = await MinioClient.putObject(env.BUCKET_NAME, fullPath, this.file.buffer, params);

			if (result.err) {
				log.e('[DriveUtil : put] File Upload Fail ', result.err);
				throw new HttpError(1101);
			}

			log.i('[DriveUtil : put] File Uplaod OK ', key);
			const resultFileData = this.createFileData(key);

			this.fastLoadFile(fullPath, extension);

			return resultFileData;
		} catch (err) {
			const tempFilePath = await this.backUpFile(fullPath);

			log.e('[DriveUtil : put] Error during upload process ', err.message);
			log.e('[DriveUtil : put] BackUp Path => ', tempFilePath);
			throw new HttpError(1123);
		}
	}

	async getHeadObjectFromCacheOrStorage(key) {
		try {
			const head = await redis.get(`driveHeadCache:${key}`);
			if (head && head !== null) {
				log.i('[DriveUtil : getHeadObjectFromCacheOrStorage] 유효한 Cache 반환');
				return head;
			}

			const response = await MinioClient.statObject(env.BUCKET_NAME, key);

			redis.set(`driveHeadCache:${key}`, response);
			log.i('[DriveUtil : getHeadObjectFromCacheOrStorage] Cache 생성');

			return response;
		} catch (err) {
			log.e('[DriveUtil : getHeadObjectFromCacheOrStorage] error : ', err.message);
			return null;
		}
	}

	createGetParams(userCacheKey) {
		return {
			Bucket: env.BUCKET_NAME,
			Key: userCacheKey,
			RequestPayer: 'requester',
		};
	}

	checkFileExist({ name }) {
		try {
			fs.accessSync(name);
			return true;
		} catch (error) {
			return false;
		}
	}

	async getObject(key, params, postfix = 'tmp') {
		// 캐시 키에 postfix(확장자) 포함: 같은 파일을 재생(.tmp)과 STT(.flac 등)가 공유하면
		// 확장자가 다른 캐시 파일을 재사용해 HAIV가 'Unsupported File'로 거부하던 문제 방지.
		const cacheKey = `${key}:${postfix}`;
		const file = await redis.get(`driveTmpFileCache:${cacheKey}`);

		if (file !== null && this.checkFileExist(file)) {
			log.i('[DriveUtil : getObject] Cache 확인');
			return file;
		}
		log.i('[DriveUtil : getObject] Cache 생성 시작');
		log.i('[DriveUtil : getObject] ', JSON.stringify(params));
		const buffer = await MinioClient.getObject(env.BUCKET_NAME, params.Key)
			.then(dataStream => dataStream)
			.catch(() => new HttpError(1102));

		const tmpFile = tmp.fileSync({ postfix: `.${postfix}`, keep: true });
		const writeStream = fs.createWriteStream(tmpFile.name);

		redis.setTmpFileAndAutoRemove(cacheKey, tmpFile);
		log.i('[DriveUtil : getObject] Cache 생성 완료 => ', cacheKey);
		await pipeline(buffer, writeStream);
		return tmpFile;
	}

	async createMinIOStream(file) {
		const userCacheKey = `${this.kms}/${file.fileKey}`;
		log.i('[DriveUtil : createMinIOStream] userCacheKey : ', userCacheKey);

		const head = await this.getHeadObjectFromCacheOrStorage(userCacheKey);
		if (!head) throw new HttpError(1122);

		const objectParams = this.createGetParams(userCacheKey);
		const tmpFile = await this.getObject(userCacheKey, objectParams);

		return { head, tmpFile, objectParams };
	}

	async removeObject({ fileKey = null }) {
		try {
			if (!fileKey) return false;
			const fullPath = `${this.kms}/${fileKey}`;
			log.i('[DriveUtil : removeObject] removeObject Start => ', fileKey);
			await MinioClient.removeObject(env.BUCKET_NAME, fullPath);
			log.i('[DriveUtil : removeObject] removeObject End => ', fileKey);
			return true;
		} catch (err) {
			return false;
		}
	}

	async putThumbnailObject(pid, type, file) {
		this.file = file;
		log.i('[DriveUtil : putThumbnail] Thumbnail Upload Start');
		const key = !type ? 'thumbnail' : type;
		const fullPath = `${pid}/${key}`;
		const encryptPath = secure.encryptECB(fullPath);
		const params = this.createPutParams();
		params['x-amz-acl'] = 'public-read';

		log.i('[DriveUtil : putThumbnail] 생성 경로 => ', encryptPath);
		const result = await MinioClient.putObject(env.PUB_BUCKET_NAME, encryptPath, this.file.buffer, params);

		if (result.err) {
			log.e('[DriveUtil : putThumbnail] Thumbnail Upload Fail ', result.err);
			throw new HttpError(1101);
		}

		const publicUrl = `https://${env.IMAGE_END_POINT}/${env.PUB_BUCKET_NAME}/${encodeURIComponent(encryptPath)}`;
		log.i('[DriveUtil : putThumbnail] Thumbnail Upload OK ', publicUrl);

		return publicUrl;
	}

	async replaceObject(fileKey, file) {
		if (!fileKey) {
			throw new HttpError(1132, 'fileKey is required');
		}
		if (!file || !file.buffer) {
			throw new HttpError(1132, 'file buffer is required');
		}

		this.file = file;
		const fullPath = `${this.kms}/${fileKey}`;
		const params = this.createPutParams();
		const extension = this.file.originalname?.split('.')[1] || 'flac';

		log.i('[DriveUtil : replaceObject] Replace Start => ', fullPath);

		try {
			const result = await MinioClient.putObject(env.BUCKET_NAME, fullPath, this.file.buffer, params);

			if (result.err) {
				log.e('[DriveUtil : replaceObject] File Replace Fail ', result.err);
				throw new HttpError(1101);
			}

			log.i('[DriveUtil : replaceObject] File Replace OK ', fileKey);

			try {
				const headCacheKey = `driveHeadCache:${fullPath}`;
				// getObject 캐시는 postfix별로 분리 저장되므로(재생 :tmp, STT :확장자) 변형까지 함께 무효화.
				const tmpFileCacheKeys = [
					`driveTmpFileCache:${fullPath}`, // 레거시(무접미사) 잔존분
					`driveTmpFileCache:${fullPath}:tmp`, // 재생/스트리밍
					`driveTmpFileCache:${fullPath}:${extension}`, // STT 등 확장자별
				];

				await redis.client.del(headCacheKey);
				await Promise.all(tmpFileCacheKeys.map(k => redis.client.del(k)));
				log.i('[DriveUtil : replaceObject] Cache invalidated');
			} catch (cacheErr) {
				log.e('[DriveUtil : replaceObject] Cache invalidation error (non-critical): ', cacheErr.message);
			}

			this.fastLoadFile(fullPath, extension);

			return true;
		} catch (err) {
			log.e('[DriveUtil : replaceObject] Error during replace process ', err.message);
			throw new HttpError(1123, `File replace failed: ${err.message}`);
		}
	}
}
