import { contentService, contentDetailService, driveService, userService } from '../../services/index.js';
import { getCalendarContents } from '../../services/feature/calendar.service.js';
import base from '../base.controller.js';
import authHandler from '../../handlers/auth.handler.js';
import { HttpError } from '../../handlers/error.handler.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';
import { stream, generate, validate } from '../../utils/index.js';

class ContentDetailController {
	async getContentDetail(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { source, tab } = req.query;
			if (!contentId) throw new HttpError(400, '파라미터가 없습니다.');
			const sourceList = ['none', 'search'];
			if (source && !sourceList.includes(source)) {
				throw new HttpError(400, `source 파라미터는 ${sourceList.join(', ')} 중 하나만 가능합니다.`);
			}

			const tabList = ['segments', 'speakerInfo', 'aiResult', 'summaryTime', 'bookmarks', 'file', 'memos'];
			const tabs = tab ? tab.split(',') : [];
			tabs?.forEach(onetab => {
				if (!tabList.includes(onetab)) {
					throw new HttpError(
						400,
						`tab 파라미터는 ${tabList.join(', ')}에 일치하는 것만 콤마로 연결하여 사용해주세요.`
					);
				}
			});

			user.permission = (await authHandler.isMoreThanContentViewer(contentId, auth, user)).role;

			const result = await contentDetailService(user, contentId, { source, tabs });
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async getAllContents(req, res, next) {
		try {
			const { user } = req;
			const options = validate.parseContentsQueryOptions(req.query);

			const contents = await contentService.getAllContents(user.pid, user.email, options);
			base.sendSuccess(res, contents);
		} catch (error) {
			next(error);
		}
	}

	async getCalendarContents(req, res, next) {
		try {
			const { user } = req;
			let { type = null, startDate, endDate, contentFilter = Enums.ContentFilter.ALL } = req.query;

			const contentFilters = Object.values(Enums.ContentFilter);
			if (!contentFilters.includes(contentFilter)) {
				throw new HttpError(1000, `contentFilter는 ${contentFilters.join(', ')} 중 하나여야 합니다.`);
			}

			if (!startDate || !endDate) {
				throw new HttpError(1000);
			}

			const regex = /^\d{8}$/;
			const isValidDate = { startDate: regex.test(startDate), endDate: regex.test(endDate) };

			if (!isValidDate.startDate || !isValidDate.endDate) {
				throw new HttpError(1110);
			}

			if (type && !Object.values(Enums.ContentType).includes(type)) {
				throw new HttpError(1000, `type은 ${Object.values(Enums.ContentType).join(', ')} 중 하나여야 합니다.`);
			}

			const options = {
				contentFilter,
				type,
				startDate: {
					year: parseInt(startDate.substring(0, 4), 10),
					month: parseInt(startDate.substring(4, 6), 10) - 1,
					day: parseInt(startDate.substring(6, 8), 10),
				},
				endDate: {
					year: parseInt(endDate.substring(0, 4), 10),
					month: parseInt(endDate.substring(4, 6), 10) - 1,
					day: parseInt(endDate.substring(6, 8), 10),
				},
			};

			const contents = await getCalendarContents(user, options);

			base.sendSuccess(res, contents);
		} catch (error) {
			next(error);
		}
	}

	async downloadContent(req, res, next) {
		try {
			const { auth, user, headers } = req;
			const { contentId } = req.params ?? req.body;

			if (contentId === undefined) throw new HttpError(1000);

			const { creatorId, workspaceId } = await authHandler.checkStreamAuth(contentId, auth, user, headers);

			// 공유받은 사용자의 경우 작성자 salt 생성
			const creatorSalt = `${creatorId}${workspaceId}`;
			auth.kms = generate.keyFromString(creatorSalt);

			const content = await contentService.findContentById(contentId);

			const streamData = await driveService.getFileStream(auth, contentId);

			new stream(streamData, req, res).response(content);
		} catch (err) {
			next(err);
		}
	}

	async exportContentToDocs(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			let { format = 'txt', include } = req.query;

			if (!contentId) throw new HttpError(1000);

			format = format.toLowerCase();
			const formatList = ['txt', 'docx', 'pdf', 'hwp'];
			if (!formatList.includes(format))
				throw new HttpError(1000, `format 파라미터는 ${formatList.join(', ')} 중 하나만 가능합니다.`);

			const includeList = ['recap', 'bookmarks', 'note', 'segments', 'highlights'];
			const includeKeys = include ? include.split(',') : includeList;
			if (includeKeys.length > 0) {
				const invalidKeys = includeKeys.filter(key => !includeList.includes(key));
				if (invalidKeys.length > 0) {
					throw new HttpError(1000, `include 파라미터는 ${includeList.join(', ')} 중 하나만 가능합니다.`);
				}
			}

			includeKeys?.forEach(oneIncludeKey => {
				if (!includeList.includes(oneIncludeKey)) {
					throw new HttpError(
						1000,
						`include 파라미터는 ${includeList.join(', ')}에 일치하는 것만 콤마로 연결하여 사용해주세요.`
					);
				}
			});

			await authHandler.isMoreThanContentDownloader(contentId, auth, user);

			const options = { format, includeKeys };
			const result = await contentService.exportContentToDocs(auth, user, contentId, options);
			const { contentType, buffer, defaultFileName, encodedFileName } = result;

			res.setHeader('Content-Type', contentType);
			res.setHeader(
				'Content-Disposition',
				`attachment; filename="${defaultFileName}"; filename*=UTF-8''${encodedFileName}`
			);

			return res.end(buffer);
		} catch (err) {
			next(err);
		}
	}

	async updateContentTitle(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { title = null } = req.body ?? req.query ?? null;

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			log.i('[ContentController : updateContentTitle] title : ', title);

			const result = contentService.updateContentTitle(contentId, title, auth, user);
			log.i('[ContentController : updateContentTitle] Success.');

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async getUsersFromDomain(req, res, next) {
		try {
			const { user } = req;
			const { keyword } = req.query;

			const domain = user.email.substring(user.email.indexOf('@'));

			const users = await userService.getUsersFromDomain(keyword, domain);

			base.sendSuccess(res, users);
		} catch (err) {
			next(err);
		}
	}
}

export default new ContentDetailController();
