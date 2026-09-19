import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class AttendeeModel extends BaseDatabase {
	constructor() {
		super('AttendeeModel');
	}

	/**
	 * @param {string} fileId
	 * @returns {Promise<speakerInfo>}
	 * @description 참석자 정보를 가져옵니다.
	 */
	async getAttendees(fileId) {
		return this.mongoDB.transcribeResult.findFirst({
			where: {
				fileId,
			},
			select: {
				speakerInfo: true,
			},
		});
	}

	/**
	 * @param {string} fileId
	 * @param {speakerInfo} speakerInfo
	 * @returns {Promise<speakerInfo>}
	 * @description 참석자 정보를 최신화(추가, 삭제)
	 */
	async updateAttendee(fileId, speakerInfo) {
		return this.mongoDB.transcribeResult.update({
			where: {
				fileId,
			},
			data: {
				speakerInfo,
			},
			select: {
				speakerInfo: true,
			},
		});
	}

	// 특정 컨텐츠 내 세그먼트별 화자 변경
	async changeSpeakerForSegment(fileId, newSpeakerId, startTimes) {
		return this.mongoDB.transcribeResult.updateMany({
			where: {
				fileId,
				segments: {
					some: {
						startTime: {
							in: startTimes,
						},
					},
				},
			},
			data: {
				mergedSegments: {
					// 세그먼트츠 필드 내부 요소 중에서
					// 다음 where 조건에 일치하는 startTime들에 한정하여,
					// 그 객체 들의 speakerId 필드에 대해서 주어진 newSpeakerId 값으로
					// 모두 업데이트
					updateMany: {
						where: {
							startTime: {
								in: startTimes,
							},
						},
						data: {
							speakerId: newSpeakerId,
						},
					},
				},
			},
		});
	}
}

export default new AttendeeModel();
