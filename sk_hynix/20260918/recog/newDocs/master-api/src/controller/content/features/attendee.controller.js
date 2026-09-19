import { attendeeService } from '../../../services/index.js';
import base from '../../base.controller.js';
import authHandler from '../../../handlers/auth.handler.js';
import { HttpError } from '../../../handlers/error.handler.js';
import { attendee } from '../../../utils/index.js';

class ContentAttendeeController {
	async getAttendees(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			if (!contentId) {
				throw new HttpError(400, '파라미터가 없습니다.');
			}
			await authHandler.isMoreThanContentViewer(contentId, auth, user);
			const result = await attendeeService.getAttendees(contentId);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async addAttendee(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			if (!contentId) throw new HttpError(1000);
			let { displayName, pid } = req.body;
			await attendee.validateAttendee(req.body);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const addAttendeeDTO = { contentId, displayName, pid, auth, user };
			const result = await attendeeService.addAttendee(addAttendeeDTO);
			base.sendCreated(res, result);
		} catch (err) {
			next(err);
		}
	}

	async changeAttendees(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			let { speakerInfo } = req.body;
			if (!contentId || !speakerInfo) throw new HttpError(1000);

			// 각 항목에 대한 검증을 Promise.all로 처리
			await Promise.all(
				speakerInfo.map(async speaker => {
					if (!speaker.speakerId) throw new HttpError(1000, 'speakerId가 없습니다.');
					await attendee.validateAttendee(speaker);
				})
			);

			const requestSpeakerIds = speakerInfo.map(attendee => attendee.speakerId);
			const uniqueRequestSpeakerIds = new Set(requestSpeakerIds);
			if (requestSpeakerIds.length !== uniqueRequestSpeakerIds.size) {
				throw new HttpError(400, '중복된 speakerId가 존재합니다.');
			}

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const attendeeDTO = { contentId, speakerInfo, auth, user };
			const result = await attendeeService.changeAttendees(attendeeDTO);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async changeAttendeeName(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, speakerId } = req.params;
			let { displayName, pid } = req.body;
			if (!contentId || !speakerId) throw new HttpError(1000);
			await attendee.validateAttendee(req.body);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const attendeeDTO = { contentId, speakerId: parseInt(speakerId), displayName, pid, auth, user };
			const result = await attendeeService.changeAttendeeName(attendeeDTO);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async deleteAttendee(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, speakerId } = req.params;
			if (!contentId || !speakerId) throw new HttpError(1000);

			await authHandler.isMoreThanContentOwner(contentId, auth, user);
			const result = await attendeeService.deleteAttendee(contentId, parseInt(speakerId), auth, user);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async changeSpeakerForSegment(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, startTime } = req.params;
			const { newSpeakerId, range } = req.body;

			if (!contentId || !startTime || !newSpeakerId || !range) {
				throw new HttpError(1000);
			}

			// newSpeakerId, startTime 양의 정수가 아닌 경우 에러
			if (isNaN(newSpeakerId) || isNaN(startTime)) {
				throw new HttpError(400, 'startTime, newSpeakerId는 양의 정수여야 합니다.');
			}

			const rangeOptionlist = ['all', 'onlyHere', 'fromHere'];

			if (!rangeOptionlist.includes(range)) {
				throw new HttpError(400, 'range는 all, onlyHere, fromHere 중 하나여야 합니다.');
			}

			await authHandler.isMoreThanContentEditor(contentId, auth, user);

			const result = await attendeeService.changeSpeakerForSegment(
				contentId,
				parseInt(startTime),
				parseInt(newSpeakerId),
				range,
				auth,
				user
			);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}
}

export default new ContentAttendeeController();

