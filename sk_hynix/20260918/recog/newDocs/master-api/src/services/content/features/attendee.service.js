import userModel from '../../../models/user.model.js';
import attendeeUtil from '../../../utils/attendee.util.js';
import contentModel from '../../../models/content.model.js';
import attendeeModel from '../../../models/attendee.model.js';
import { HttpError } from '../../../handlers/error.handler.js';
import contentCaptureService from '../contentCapture.service.js';

class AttendeeService {
	constructor() {
		this.userModel = userModel;
		this.attendeeUtil = attendeeUtil;
		this.contentModel = contentModel;
		this.attendeeModel = attendeeModel;
		this.contentCaptureService = contentCaptureService;
	}

	// 컨텐츠의 참석자 목록 조회
	async getAttendees(contentId) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId);

			const { speakerInfo } = await this.attendeeModel.getAttendees(file.id);
			if (!speakerInfo) {
				throw new HttpError(1121); // '아직 전사 결과가 없습니다.'
			}

			return await this.matchProfileBySpeakerInfo(speakerInfo);
		} catch (err) {
			throw err;
		}
	}

	// 컨텐츠의 참석자 맵핑 정보 매칭
	async matchProfileBySpeakerInfo(speakerInfo) {
		try {
			const pids = speakerInfo.map(attendee => attendee.pid)?.filter(pid => pid);

			if (!pids.length) return { speakerInfo };

			const members = await this.userModel.getUserInfosByUserIds(pids);

			speakerInfo.forEach(attendee => {
				const member = members.find(member => member.pid === attendee.pid);
				if (!member) return;
				const { nickName, email, thumbnailUrl } = member;
				attendee.displayName = nickName;
				attendee.email = email;
				attendee.thumbnailUrl = thumbnailUrl;
			});

			return { speakerInfo };
		} catch (err) {
			throw err;
		}
	}

	// 컨텐츠 참석자 추가
	async addAttendee(addAttendeeDTO) {
		try {
			const { contentId, displayName, pid, auth, user } = addAttendeeDTO;
			const file = await this.contentModel.findFileByContentId(contentId, { transcribeResult: true });
			const { speakerInfo } = await this.findAttendeeByPid(file.id, pid);

			// 마지막 요소 확인을 위한 불필요한 순회 제거
			const speakerIds = speakerInfo.map(attendee => attendee.speakerId);
			const maxSpeakerId = Math.max(...speakerIds);

			const defaultNamePrefix = this.attendeeUtil.getLangPrefix(file.transcribeResult?.clientLanguage);

			speakerInfo.push({
				speakerId: maxSpeakerId + 1,
				name: `${defaultNamePrefix} ${maxSpeakerId + 1}`,
				displayName: pid ? null : displayName,
				pid: pid || null,
			});

			const result = await this.attendeeModel.updateAttendee(file.id, speakerInfo);

			await this.contentCaptureService.createContentCapture(
				'CONTENT',
				'UPDATE_ATTENDEE',
				contentId,
				auth.member.id,
				user,
				speakerInfo.length
			);

			return await this.matchProfileBySpeakerInfo(result.speakerInfo);
		} catch (err) {
			throw err;
		}
	}

	// 컨텐츠 참석자 validation Service
	async findAttendeeByPid(fileId, pid) {
		try {
			const [{ speakerInfo }, member] = await Promise.all([
				this.attendeeModel.getAttendees(fileId),
				pid && this.userModel.getUserInfoByUserId(pid),
			]);

			if (!speakerInfo) throw new HttpError(1121); // '아직 전사 결과가 없습니다.'
			if (pid && !member) throw new HttpError(1500); // '사용자 정보를 조회할 수 없는 pid입니다.'
			if (pid && speakerInfo.find(attendee => attendee.pid === pid)) throw new HttpError(1504); // 이미 참석자로 설정한 pid를 중복 요청했습니다.

			return { speakerInfo, member };
		} catch (err) {
			throw err;
		}
	}

	// 컨텐츠 참석자 이름 변경
	async changeAttendeeName({ contentId, speakerId, displayName, pid, auth, user }) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId);
			const { speakerInfo } = await this.findAttendeeByPid(file.id, pid);

			const targetAttendee = speakerInfo.find(attendee => attendee.speakerId === speakerId);
			if (!targetAttendee) throw new HttpError(1501); // 'speakerInfo에 해당하는 참석자가 존재하지 않습니다.'
			if (targetAttendee.displayName === displayName) throw new HttpError(1502); // '변경하려는 이름이 기존 이름과 동일합니다.'

			targetAttendee.pid = pid || null;
			targetAttendee.displayName = pid ? null : displayName;

			const result = await this.attendeeModel.updateAttendee(file.id, speakerInfo);

			await this.contentCaptureService.createContentCapture(
				'CONTENT',
				'UPDATE_ATTENDEE',
				contentId,
				auth.member.id,
				user,
				speakerInfo.length
			);

			return await this.matchProfileBySpeakerInfo(result.speakerInfo);
		} catch (err) {
			throw err;
		}
	}

	// 컨텐츠 참석자 이름 다중 변경
	async changeAttendees({ contentId, speakerInfo: newSpeakerInfo, auth, user }) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId, { transcribeResult: true });
			const [{ speakerInfo: baseSpeakerInfo }, { mergedSegments }] = await Promise.all([
				this.attendeeModel.getAttendees(file.id),
				this.contentModel.getSegments(file.id),
			]);

			const newSpeakerIdSet = new Set(newSpeakerInfo.map(s => s.speakerId));
			const baseSpeakerIdSet = new Set(baseSpeakerInfo.map(a => a.speakerId));
			const newSpeakerMap = new Map(newSpeakerInfo.map(a => [a.speakerId, a]));
			const mergedSpeakerIdSet = new Set(mergedSegments.map(seg => seg.speakerId));

			const assignedSpeakerIdSet = new Set();
			baseSpeakerInfo.forEach(attendee => {
				if (mergedSpeakerIdSet.has(attendee.speakerId)) {
					assignedSpeakerIdSet.add(attendee.speakerId);
				}
			});

			const missingSpeakers = [...assignedSpeakerIdSet].filter(id => !newSpeakerIdSet.has(id));
			if (missingSpeakers.length > 0) {
				throw new HttpError(1505, `필수 참석자 누락 id : ${missingSpeakers.join(', ')}`);
			}

			const defaultNamePrefix = this.attendeeUtil.getLangPrefix(file.transcribeResult?.clientLanguage);

			const finalSpeakerInfo = [];

			// 1. 기존 참석자 처리 (로직 동일)
			baseSpeakerInfo.forEach(baseAttendee => {
				const isInNewList = newSpeakerIdSet.has(baseAttendee.speakerId);
				const isAssigned = assignedSpeakerIdSet.has(baseAttendee.speakerId);

				if (isInNewList || isAssigned) {
					const updatedAttendee = { ...baseAttendee };
					const newAttendeeData = newSpeakerMap.get(updatedAttendee.speakerId);

					if (newAttendeeData) {
						if (newAttendeeData.displayName === null) {
							updatedAttendee.displayName = null;
							updatedAttendee.pid = null;
						} else {
							updatedAttendee.displayName = newAttendeeData.displayName;
						}
					}
					finalSpeakerInfo.push(updatedAttendee);
				}
			});

			// 2. 새로운 참석자 추가 (로직 동일, defaultNamePrefix 사용)
			newSpeakerInfo.forEach(newAttendee => {
				if (!baseSpeakerIdSet.has(newAttendee.speakerId)) {
					finalSpeakerInfo.push({
						speakerId: newAttendee.speakerId,
						name: `${defaultNamePrefix} ${newAttendee.speakerId}`,
						displayName: newAttendee.displayName,
						pid: newAttendee.pid || null,
					});
				}
			});

			finalSpeakerInfo.sort((a, b) => a.speakerId - b.speakerId);

			const result = await this.attendeeModel.updateAttendee(file.id, finalSpeakerInfo);

			await this.contentCaptureService.createContentCapture(
				'CONTENT',
				'UPDATE_ATTENDEE',
				contentId,
				auth.member.id,
				user,
				finalSpeakerInfo.length
			);

			return await this.matchProfileBySpeakerInfo(result.speakerInfo);
		} catch (err) {
			throw err;
		}
	}

	// 컨텐츠 참석자 삭제
	async deleteAttendee(contentId, speakerId, { member }, user) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId);

			const [{ speakerInfo }, { mergedSegments }] = await Promise.all([
				this.attendeeModel.getAttendees(file.id),
				this.contentModel.getSegments(file.id),
			]);
			if (!speakerInfo) throw new HttpError(1121); // '아직 전사 결과가 없습니다.'
			const attendeeIndex = speakerInfo.findIndex(attendee => attendee.speakerId === speakerId);
			if (attendeeIndex === -1) throw new HttpError(1501); // '참석자가 존재하지 않습니다.'

			const isSpeakerAssigned = mergedSegments.some(segment => segment.speakerId === speakerId);
			const attendee = speakerInfo[attendeeIndex];

			if (isSpeakerAssigned) {
				throw new HttpError(1503);
				// const isSystemAssignedSpeaker = !attendee.displayName;
				// if (isSystemAssignedSpeaker) // '화자 설정된 기본 참석자는 완전히 삭제 불가'
				// attendee.displayName = null;
				// attendee.pid = null;
			} else {
				speakerInfo.splice(attendeeIndex, 1);
			}

			const result = await this.attendeeModel.updateAttendee(file.id, speakerInfo);

			await this.contentCaptureService.createContentCapture(
				'CONTENT',
				'UPDATE_ATTENDEE',
				contentId,
				member.id,
				user,
				speakerInfo.length
			);

			return await this.matchProfileBySpeakerInfo(result.speakerInfo);
		} catch (err) {
			throw err;
		}
	}

	// segment(음성 기록)별 화자 변경
	async changeSpeakerForSegment(contentId, startTime, newSpeakerId, range, { member }, user) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId);

			// 수정 포인트: 속도 개선을 위해 특정 speakerId에 대해서만 쿼리하는 것이 필요할 수 있음
			const [{ speakerInfo }, { mergedSegments }] = await Promise.all([
				this.attendeeModel.getAttendees(file.id),
				this.contentModel.getSegments(file.id),
			]);

			if (!speakerInfo || !mergedSegments) {
				throw new HttpError(1121); // '전사된 음성 기록이 없습니다.'
			}

			const [existedAttendee, existedSegment] = await Promise.all([
				speakerInfo.find(attendee => attendee.speakerId === newSpeakerId),
				mergedSegments.find(segment => segment.startTime === startTime),
			]);

			if (!existedAttendee) throw new HttpError(1501); // 'speakerInfo에 해당하는 참석자가 존재하지 않습니다.'
			if (!existedSegment) throw new HttpError(1120); // '해당 시간대의 음성 기록을 찾을 수 없습니다.'

			const startTimes = [];

			mergedSegments.map(segment => {
				if (range === 'onlyHere') {
					if (segment.startTime === startTime) {
						startTimes.push(segment.startTime);
					}
				}

				if (range === 'fromHere') {
					if (segment.startTime >= startTime && segment.speakerId === existedSegment.speakerId) {
						startTimes.push(segment.startTime);
					}
				}

				if (range === 'all') {
					if (segment.speakerId === existedSegment.speakerId) {
						startTimes.push(segment.startTime);
					}
				}
			});

			const result = await this.attendeeModel.changeSpeakerForSegment(file.id, newSpeakerId, startTimes);

			if (!result) {
				throw new HttpError(500, '음성 기록 세그먼트 변경 실패');
			}

			const changedSegments = await this.contentModel.getSegments(file.id);
			// const remergedSegments = convert.mergedSegments(changedSegments.mergedSegments);
			// this.contentModel.updateMergedSegments(file.id, remergedSegments);

			await this.contentCaptureService.createContentCapture(
				'CONTENT',
				'UPDATE_SEGMENT',
				contentId,
				member.id,
				user
			);

			return {
				changedCount: startTimes.length,
				changedStartTimes: startTimes,
				mergedSegments: changedSegments.mergedSegments,
				// remergedSegments,
			};
		} catch (err) {
			throw err;
		}
	}
}

export default new AttendeeService();
