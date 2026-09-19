import multer from 'multer';
import path from 'path';
import { HttpError } from '../../handlers/error.handler.js';

let uploadTimeout = 3 * 60 * 60 * 1000;
process.on('configChanged', () => {
	uploadTimeout = process.env.UPLOAD_TIMEOUT || 3 * 60 * 60 * 1000;
});

const ALLOWED_IMAGE_MIME_TYPES = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/bmp'];
const ALLOWED_IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.bmp'];
const DENIED_IMAGE_PATTERNS = [
	/<script/i,
	/<\?php/i,
	/<%/i,
	/javascript:/i,
	/vbscript:/i,
	/data:/i,
	/onload=/i,
	/onerror=/i,
	/onclick=/i,
	/onmouseover=/i,
	/eval\(/i,
	/exec\(/i,
	/system\(/i,
	/parse_ini_file\(/i,
	/\.\.\//i,
	/\.\.\\/i,
	/%2e%2e%2f/i,
	/%2e%2e%5c/i,
	/%00/i,
	/cmd\s*\/c/i,
	/\/bin\/sh/i,
	/powershell/i,
];

const sanitizeFileName = filename => {
	// 경로 탐색 문자 제거 (../, ..\, ..\ 등)
	let sanitized = filename.replace(/\.\.+[\/\\]/g, '');

	// 연속된 점 제거 (경로 탐색 방지)
	sanitized = sanitized.replace(/\.{2,}/g, '.');
	sanitized = sanitized.replace(/\s{2,}/g, '.');

	// NULL 바이트 및 URL 인코딩된 NULL 바이트 제거 (%00)
	sanitized = sanitized.replace(/\x00/g, '').replace(/%00/gi, '');

	// 위험한 특수 문자 제거 (..\, .\, %, ;, 공백 등)
	sanitized = sanitized.replace(/[\/\\:*?"<>|%;]/g, '');

	// 연속된 공백을 단일 공백으로 변환 후 앞뒤 공백 제거
	sanitized = sanitized.replace(/\s+/g, ' ').trim();

	// 파일명이 점으로 시작하는 것 방지 (숨김 파일)
	if (sanitized.startsWith('.')) {
		sanitized = sanitized.substring(1);
	}

	// 파일명 길이 제한
	if (sanitized.length > 500) {
		const ext = path.extname(sanitized);
		const name = path.basename(sanitized, ext);
		sanitized = name.substring(0, 500 - ext.length) + ext;
	}
	return sanitized;
};

const imageValidator = file => {
	if (!ALLOWED_IMAGE_MIME_TYPES.includes(file.mimetype)) {
		log.i('ALLOWED_IMAGE_MIME_TYPES', file.mimetype);
		return false;
	}

	const fileName = sanitizeFileName(file.originalname);
	const extension = path.extname(fileName).toLowerCase();
	log.i('extension', extension);
	if (!ALLOWED_IMAGE_EXTENSIONS.includes(extension)) {
		log.i('ALLOWED_IMAGE_EXTENSIONS', file.originalname);
		return false;
	}

	if (DENIED_IMAGE_PATTERNS.some(pattern => pattern.test(fileName))) {
		log.i('DENIED_IMAGE_PATTERNS', file.originalname);
		return false;
	}

	file.originalname = fileName;

	return true;
};

class multerUtil {
	uploadFile() {
		return multer({
			limits: {
				fileSize: 2 * 1024 * 1024 * 1024,
			},
		}).single('file');
	}

	uploadFiles() {
		return multer({
			limits: {
				fileSize: 2 * 1024 * 1024 * 1024,
			},
		}).array('files');
	}

	uploadTextFile() {
		return multer({
			limits: {
				fileSize: 10 * 1024 * 1024,
			},
			fileFilter: (req, file, cb) => {
				if (file.mimetype === 'text/plain') {
					cb(null, true);
				} else {
					cb(new HttpError(1109, '지원하지 않는 파일 형식입니다. (.txt 파일만 가능합니다)'), false);
				}
			},
		}).single('file');
	}

	uploadImageFile() {
		return multer({
			limits: {
				fileSize: 10 * 1024 * 1024,
			},
			fileFilter: (req, file, cb) => {
				if (imageValidator(file)) {
					cb(null, true);
				} else {
					cb(new HttpError(1109), false);
				}
			},
		}).single('image');
	}

	uploadContactFile() {
		return multer({
			storage: multer.memoryStorage(),
			limits: {
				fileSize: 10 * 1024 * 1024, // 10MB 제한
			},
			fileFilter: (req, file, cb) => {
				// CSV와 XLSX 파일 모두 허용
				const extension = path.extname(file.originalname).toLowerCase();
				const allowedExtensions = ['.csv', '.xlsx'];
				const allowedMimes = [
					'text/csv',
					'application/csv',
					'text/plain',
					'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
				];

				if (allowedExtensions.includes(extension) || allowedMimes.includes(file.mimetype)) {
					cb(null, true);
				} else {
					cb(
						new HttpError(1000, '지원하지 않는 파일 형식입니다. (.csv 또는 .xlsx 파일만 가능합니다)'),
						false
					);
				}
			},
		}).single('file');
	}

	// 타임아웃이 적용된 업로드 함수들
	uploadFileWithTimeout() {
		const upload = this.uploadFile();
		return (req, res, next) => {
			const timer = setTimeout(() => {
				const u = req.user || {};
				log.i(
					`[multer] Upload timeout after ${uploadTimeout}ms ` +
						`email=${u.email ?? '-'} pid=${u.pid ?? '-'} ` +
						`ip=${req.ip ?? '-'} remoteAddress=${req.socket?.remoteAddress ?? '-'} ` +
						`contentLength=${req.headers['content-length'] ?? '-'} bytesRead=${req.socket?.bytesRead ?? '-'}`
				);
				if (!res.headersSent) {
					res.status(200).json({
						message: '업로드 시간이 초과되었습니다.',
						httpCode: 408,
					});
				}
			}, uploadTimeout);
			upload(req, res, err => {
				clearTimeout(timer); // 업로드가 끝나면 타이머 해제
				if (err) return next(err);
				next();
			});
		};
	}

	uploadFilesWithTimeout() {
		const upload = this.uploadFiles();
		return (req, res, next) => {
			const timer = setTimeout(() => {
				const u = req.user || {};
				log.i(
					`[multer] Upload timeout after ${uploadTimeout}ms ` +
						`email=${u.email ?? '-'} pid=${u.pid ?? '-'} ` +
						`ip=${req.ip ?? '-'} remoteAddress=${req.socket?.remoteAddress ?? '-'} ` +
						`contentLength=${req.headers['content-length'] ?? '-'} bytesRead=${req.socket?.bytesRead ?? '-'}`
				);
				if (!res.headersSent) {
					res.status(200).json({
						message: '업로드 시간이 초과되었습니다.',
						httpCode: 408,
					});
				}
			}, uploadTimeout);
			upload(req, res, err => {
				clearTimeout(timer); // 업로드가 끝나면 타이머 해제
				if (err) return next(err);
				next();
			});
		};
	}
}

export default new multerUtil();
