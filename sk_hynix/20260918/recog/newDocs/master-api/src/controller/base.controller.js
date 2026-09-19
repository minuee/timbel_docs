import { Enums } from '@timbel-timblo-onpremise/prisma';

class BaseController {
	// Enums Export

	/// Enums.ContentShareRole
	ContentShareRoleValues = Object.values(Enums.ContentShareRole);
	OWNER = Enums.ContentShareRole.OWNER;
	VIEWER = Enums.ContentShareRole.VIEWER;

	/// Enums.ContentType
	AUDIO = Enums.ContentType.AUDIO;
	RECORD = Enums.ContentType.RECORD;
	TEXT = Enums.ContentType.TEXT;

	/// Enums.BookmarksKeys
	BookmarksKeyValues = Object.values(Enums.BookmarksKeys);

	/// Enums.MemoKeys
	MemoKeyValues = Object.values(Enums.MemoKeys);

	/**
	 * 성공 응답 포맷팅
	 * @param {Object} res - Express response 객체
	 * @param {*} data - 응답 데이터
	 * @param {number} httpCode - HTTP 상태 코드 (기본값: 200)
	 * @param {string} message - 응답 메시지 (기본값: 'Success')
	 */
	sendSuccess(res, data = {}, httpCode = 200, message = 'Success') {
		res.json({ message, httpCode, data });
	}

	/**
	 * 성공 응답 (201 Created)
	 * @param {Object} res - Express response 객체
	 * @param {*} data - 응답 데이터
	 * @param {string} message - 응답 메시지 (기본값: 'Success')
	 */
	sendCreated(res, data = {}, message = 'Success') {
		this.sendSuccess(res, data, 201, message);
	}

	/**
	 * 성공 응답 (204 No Content)
	 * @param {Object} res - Express response 객체
	 */
	sendNoContent(res) {
		res.json({ message: 'Success', httpCode: 204, data: {} });
	}
}

export default new BaseController();
