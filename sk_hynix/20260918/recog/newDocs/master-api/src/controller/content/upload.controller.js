import { driveService } from '../../services/index.js';
import base from '../base.controller.js';
import folderUtils from '../../utils/folder.util.js';
import authHandler from '../../handlers/auth.handler.js';
import { HttpError } from '../../handlers/error.handler.js';
import { convert, validate } from '../../utils/index.js';

class ContentUploadController {
	async uploadContent(req, res, next) {
		try {
			let { auth, file, user } = req;
			let {
				isRecord,
				lang = 'ko',
				attendeeNum = 0,
				type = base.AUDIO,
				summary = 'medium',
				folderId = null,
				templateId = null,
				manual = {},
			} = req.body ?? req.query ?? null;

			log.i('[ContentController : uploadContent] lang : ', lang);
			if (lang === 'none') lang = auth.config.lang;

			if (!file) throw new HttpError(1000);
			authHandler.isMember(auth);

			auth.config.transcribeLang = lang === 'koen' ? 'ko' : lang;
			auth.config.summarySize = summary;

			if (process.env.USE_LLM_MODEL === 'skax-template')
				auth.config.templateId = templateId ?? 'DEF-DEFAULT-BASIC';

			if (auth.config?.external) {
				const { email, chatId } = auth.config.external;
				if (email.startsWith('rec_system_') && email.split('@')[1] === 'adotbiz.ai' && !chatId)
					throw new HttpError(1000);
			}

			if (file.originalname.includes('.wav')) {
				log.i('[ContentController : uploadContent] wav 파일 압축 변환 시작');
				file = await convert.replaceFileWithFlac(file);
				log.i('[ContentController : uploadContent] wav 파일 압축 변환 완료');
			}

			file.folderId = folderId === 'null' ? undefined : folderId;
			file.attendeeNum = attendeeNum;
			file.originalname = convert.originalnameEncoding(file);
			file.isRecord = isRecord ? isRecord.trim().toUpperCase() === 'TRUE' : undefined;

			if (type === 'record') file.inputType = base.RECORD;

			if (folderId && folderUtils.getVirtualFolderIds().includes(folderId)) {
				file.folderId = null; // 가상 폴더로 업로드 요청시  folderId = null로 만들기
			}

			const result = await driveService.uploadContent(file, auth, user, manual);

			if (result.hasOwnProperty('content')) {
				result['content']['creatorPID'] = user.pid;
				result['content']['creatorNickName'] = user.nickName;
				result['content']['creatorThumbnailUrl'] = user.thumbnailUrl;
			}

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async uploadEncryptionFileContent(req, res, next) {
		try {
			const { auth, file, user } = req;
			let {
				lang = 'ko',
				attendeeNum = 0,
				deviceId,
				fileName,
				num,
				totalNum,
				end,
				templateId = null,
			} = req.body ?? req.query ?? null;

			log.i('[ContentController : uploadEncryptionFileContent] body', req.body);

			log.i('[ContentController : uploadEncryptionFileContent] lang : ', lang);
			if (lang === 'none') lang = auth.config.lang;

			if (!file || !deviceId || !fileName || !num || !totalNum) throw new HttpError(1000);
			authHandler.isMember(auth);

			auth.config.transcribeLang = lang;

			// 모바일 암호화 업로드도 템플릿 선택 반영 (단일/텍스트 업로드와 동일 패턴)
			if (process.env.USE_LLM_MODEL === 'skax-template')
				auth.config.templateId = templateId ?? 'DEF-DEFAULT-BASIC';

			const fileInfo = {
				deviceId,
				fileName,
				num,
				totalNum,
				end,
				attendeeNum,
				'originalnames': [convert.originalnameEncoding(file)],
			};

			log.i('[ContentController : uploadEncryptionFileContent] fileInfo', fileInfo);
			const result = await driveService.uploadEncryptionContent([file], fileInfo, auth, user);

			if (result.hasOwnProperty('content')) {
				result['content']['creatorPID'] = user.pid;
				result['content']['creatorNickName'] = user.nickName;
				result['content']['creatorThumbnailUrl'] = user.thumbnailUrl;
			}

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async uploadEncryptionFilesContent(req, res, next) {
		try {
			const { auth, files, user } = req;
			let { lang = 'ko', attendeeNum = 0, deviceId, fileName, totalNum, manual, templateId = null } = req.body ?? req.query ?? null;

			log.i('[ContentController : uploadEncryptionFilesContent] body', req.body);

			log.i('[ContentController : uploadContent] lang : ', lang);
			if (lang === 'none') lang = auth.config.lang;

			if (!files || !deviceId || !fileName || !totalNum) throw new HttpError(1000);
			authHandler.isMember(auth);

			log.i('[uploadEncryptionFilesContent] files : ', files.length);

			auth.config.transcribeLang = lang;

			// 모바일 암호화 업로드도 템플릿 선택 반영 (단일/텍스트 업로드와 동일 패턴)
			if (process.env.USE_LLM_MODEL === 'skax-template')
				auth.config.templateId = templateId ?? 'DEF-DEFAULT-BASIC';

			const filesInfo = {
				deviceId,
				fileName,
				totalNum,
				attendeeNum,
				'originalnames': files.map(file => convert.originalnameEncoding(file)),
			};
			log.i('[ContentController : uploadEncryptionFilesContent] filesInfo', filesInfo);

			const manualOptions = manual ? JSON.parse(manual) : {};
			const result = await driveService.uploadEncryptionContent(files, filesInfo, auth, user, manualOptions);

			if (result.hasOwnProperty('content')) {
				result['content']['creatorPID'] = user.pid;
				result['content']['creatorNickName'] = user.nickName;
				result['content']['creatorThumbnailUrl'] = user.thumbnailUrl;
			}

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async uploadThumbnail(req, res, next) {
		try {
			const {
				user: { pid },
				auth,
				file,
			} = req;
			const { type = 'thumbnail' } = req.body ?? req.query ?? null;

			log.i('[ContentController : uploadThumbnail] auth : ', auth);
			if (!pid) throw new HttpError(401);
			if (!file) throw new HttpError(1000);
			file.originalname = convert.originalnameEncoding(file);
			if (!validate.validateMagicByte(file)) throw new HttpError(1109);
			if (!auth || !auth.isAuthorized) throw new HttpError(1002);

			const result = await driveService.uploadThumbnail(pid, file, type);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async uploadTextFileContent(req, res, next) {
		try {
			const { auth, file, user } = req;
			let {
				lang = 'ko',
				templateId = null,
				summary = 'medium',
				chunkSize = process.env.SKAX_TEXT_SPLITTER_CHUNK_SIZE ?? 500,
			} = req.body ?? req.query ?? null;

			log.i('[ContentController : uploadContent] lang : ', lang);
			if (lang === 'none') lang = auth.config.lang;

			if (!file) throw new HttpError(1000);
			authHandler.isMember(auth);

			auth.config.transcribeLang = lang === 'koen' ? 'ko' : lang;
			auth.config.summarySize = summary;

			if (process.env.USE_LLM_MODEL === 'skax-template')
				auth.config.templateId = templateId ?? 'DEF-DEFAULT-BASIC';

			file.originalname = convert.originalnameEncoding(file);
			file.inputType = base.TEXT;
			file.chunkSize = chunkSize ?? null;

			const result = await driveService.uploadTextFileContent(file, auth, user);

			if (result.hasOwnProperty('content')) {
				result['content']['creatorPID'] = user.pid;
				result['content']['creatorNickName'] = user.nickName;
				result['content']['creatorThumbnailUrl'] = user.thumbnailUrl;
			}

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}
}

export default new ContentUploadController();
