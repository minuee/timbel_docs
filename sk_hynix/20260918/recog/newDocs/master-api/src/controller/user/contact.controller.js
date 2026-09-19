import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import { userService } from '../../services/index.js';
import { validate, convert } from '../../utils/index.js';
import contactBulkUtils from '../../utils/contact/bulk.util.js';

class UserContactController {
	async createContact(req, res, next) {
		try {
			const { user } = req;
			let { email, department = '', position = '', memo = '', labelIds = [] } = req.body;

			if (!email.trim()) throw new HttpError(1000, '이메일을 입력해주세요');

			validate.emailRegexValidate(email);

			department = department.trim();
			position = position.trim();
			memo = memo.trim();

			const createContactDTO = { pid: user.pid, email, department, position, memo, labelIds };
			const result = await userService.createContact(createContactDTO);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async createBulkContacts(req, res, next) {
		try {
			const { user } = req;
			const excelFile = req.file; // multer로 업로드된 파일
			let { emails = [], users = [] } = req.body;

			// multipart/form-data에서의 배열 파싱 처리
			if (typeof emails === 'string') {
				emails = emails ? JSON.parse(emails) : [];
			}
			if (typeof users === 'string') {
				users = users ? JSON.parse(users) : [];
			}

			if (!users.length && !emails.length && !excelFile) {
				throw new HttpError(1000, '사용자 정보, 이메일 배열 또는 엑셀 파일을 입력해주세요');
			}

			// emails 배열이 있으면 users에 추가 (index 포함)
			if (emails?.length > 0) {
				emails.forEach((email, idx) => {
					users.push({
						index: users.length + idx + 2, // 2번 행부터 시작 (1번 행은 헤더)
						email,
						label1: '',
						label2: '',
						label3: '',
						label4: '',
						label5: '',
						memo: '',
					});
				});
			}

			// 파일이 있으면 읽어서 users에 추가 (CSV/XLSX 자동 감지)
			if (excelFile) {
				const fileData = await contactBulkUtils.readContactFile(excelFile);
				users.push(...fileData);
			}

			const createContactDTO = { pid: user.pid, users };
			const result = await userService.createBulkContacts(createContactDTO);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async downloadContactTemplate(req, res, next) {
		try {
			const { format = 'csv' } = req.query; // 기본값: csv

			let buffer;
			let filename;
			let contentType;

			if (format === 'xlsx') {
				// XLSX 양식 (옵션)
				buffer = await contactBulkUtils.generateContactTemplate();
				filename = 'contact_bulk.xlsx';
				contentType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
			} else {
				// CSV 양식 (기본)
				buffer = await contactBulkUtils.generateContactTemplateCSV();
				filename = 'contact_bulk.csv';
				contentType = 'text/csv; charset=utf-8';
			}

			res.setHeader('Content-Type', contentType);
			res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
			res.setHeader('Content-Length', buffer.length);

			res.send(buffer);
		} catch (err) {
			next(err);
		}
	}

	async getContacts(req, res, next) {
		try {
			const { user } = req;
			let {
				page,
				take,
				isFavorite,
				isRecycle,
				labelId = null,
				sort = validate.sortConfig.domain.contact.defaultField,
				direction = validate.sortConfig.domain.contact.defaultDirection,
			} = req.query;

			const parseBooleanQuery = value => {
				if (value === undefined) return undefined;
				if (value === 'true') return true;
				if (value === 'false') return false;
				return undefined;
			};

			const parseBooleanQueryOrDefault = (value, defaultValue) => {
				const parsed = parseBooleanQuery(value);
				return parsed === undefined ? defaultValue : parsed;
			};

			isFavorite = parseBooleanQuery(isFavorite);
			isRecycle = parseBooleanQueryOrDefault(isRecycle, false);
			labelId = labelId ? labelId : null;

			validate.sortValidate(sort, 'contact');
			validate.sortDirectionValidate(direction);

			const options = {
				page: page ? parseInt(page) : validate.sortConfig.paging.default.page,
				take: take ? parseInt(take) : validate.sortConfig.paging.default.take,
				sort,
				direction,
				isFavorite,
				isRecycle,
				labelId,
			};

			const data = await userService.getContacts(user, options);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async deleteContact(req, res, next) {
		try {
			const { user } = req;
			const { contactId } = req.params;

			if (!contactId) throw new HttpError(1000, '주소록 아이디를 전달해주세요');

			await userService.deleteContact(user, contactId);

			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async deleteContacts(req, res, next) {
		try {
			const { user } = req;
			let { contactIds = [] } = req.body;

			if (!contactIds?.length) throw new HttpError(1000, '주소록 아이디는 배열로 전달해주세요');

			await userService.deleteContacts(user, contactIds);
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async updateContact(req, res, next) {
		try {
			const { user } = req;
			const { contactId } = req.params;
			const { memo, labelIds } = req.body;

			if (!contactId) throw new HttpError(1000);
			if (memo === undefined && labelIds === undefined)
				throw new HttpError(1000, '수정할 내용을 전달해주세요 (memo 또는 labelIds)');
			if (labelIds !== undefined && !Array.isArray(labelIds))
				throw new HttpError(1000, '라벨 ID는 배열로 전달해주세요');
			if (labelIds !== undefined && labelIds.length > 5)
				throw new HttpError(1000, '라벨 ID는 최대 5개까지 전달할 수 있습니다');

			const data = await userService.updateContact(user, contactId, { memo, labelIds });

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async updateContactFavorite(req, res, next) {
		try {
			const { user } = req;
			let { isFavorite = false, contactIds = [] } = req.body;

			if (!contactIds?.length) throw new HttpError(1000, '주소록 아이디는 배열로 전달해주세요');

			if (typeof isFavorite !== 'boolean')
				throw new HttpError(1000, '즐겨찾기 여부를 boolean 타입으로 전달해주세요');

			await userService.updateContactFavorite(user, contactIds, isFavorite);
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async updateContactRecycle(req, res, next) {
		try {
			const { user } = req;
			let { isRecycle = false, contactIds = [] } = req.body;

			if (!contactIds?.length) throw new HttpError(1000, '주소록 아이디는 배열로 전달해주세요');

			if (typeof isRecycle !== 'boolean')
				throw new HttpError(1000, '휴지통 이동 여부를 boolean 타입으로 전달해주세요');

			await userService.updateContactRecycle(user, contactIds, isRecycle);
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async searchContacts(req, res, next) {
		try {
			const { user } = req;
			let {
				keyword,
				page,
				take,
				sort = validate.sortConfig.domain.contact.defaultField,
				direction = validate.sortConfig.domain.contact.defaultDirection,
			} = req.query;

			if (!keyword.trim()) throw new HttpError(1000, '검색어를 입력해주세요.');

			validate.sortValidate(sort, 'contact');
			validate.sortDirectionValidate(direction);

			keyword = convert.keywordTransform(keyword);

			const options = {
				page: page ? parseInt(page) : validate.sortConfig.paging.default.page,
				take: take ? parseInt(take) : validate.sortConfig.paging.default.take,
				sort,
				direction,
			};

			const data = await userService.searchContacts(user, { keyword, ...options });
			base.sendSuccess(res, { keyword, ...data });
		} catch (err) {
			next(err);
		}
	}

	async createContactLabel(req, res, next) {
		try {
			const { user } = req;
			const { name, color = '#FFFFFF' } = req.body;

			if (!name || !name.trim()) throw new HttpError(1000, '라벨 이름을 입력해주세요');

			const trimmedName = name.trim();
			if (trimmedName.length > 128) throw new HttpError(1000, '라벨 이름은 128자를 초과할 수 없습니다');

			if (color?.length > 7) throw new HttpError(1000, '라벨 색상은 #FFFFFF 형식으로 입력해주세요');
			if (!color?.startsWith('#')) throw new HttpError(1000, '라벨 색상은 #으로 시작해주세요');

			const result = await userService.createContactLabel(user, trimmedName, color);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async getContactLabels(req, res, next) {
		try {
			const { user } = req;

			const result = await userService.getContactLabels(user);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async deleteContactLabel(req, res, next) {
		try {
			const { user } = req;
			const { labelId } = req.params;

			if (!labelId) throw new HttpError(1000, '라벨 아이디를 전달해주세요');

			await userService.deleteContactLabel(user, labelId);

			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async updateContactLabel(req, res, next) {
		try {
			const { user } = req;
			const { labelId } = req.params;
			const { name, color } = req.body;

			if (!labelId || !color) throw new HttpError(1000, '라벨 아이디와 색상을 함께 전달해주세요');

			const trimmedName = name.trim();
			if (trimmedName.length > 128) throw new HttpError(1000, '라벨 이름은 128자를 초과할 수 없습니다');

			if (color?.length > 7) throw new HttpError(1000, '라벨 색상은 #FFFFFF 형식으로 입력해주세요');
			if (!color?.startsWith('#')) throw new HttpError(1000, '라벨 색상은 #으로 시작해주세요');

			const result = await userService.updateContactLabel(user, labelId, trimmedName, color);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async updateContactLabeling(req, res, next) {
		try {
			const { user } = req;
			const { contactIds, labelIds } = req.body;

			if (!Array.isArray(contactIds) || contactIds.length === 0)
				throw new HttpError(1000, '주소록 ID는 배열로 전달해주세요');
			if (!Array.isArray(labelIds) || labelIds.length === 0)
				throw new HttpError(1000, '라벨 ID는 배열로 전달해주세요');
			if (labelIds.length > 5) throw new HttpError(1000, '라벨 ID는 최대 5개까지 전달할 수 있습니다');

			await userService.updateContactLabelingBatch(user, contactIds, labelIds);

			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}
}

export default new UserContactController();
