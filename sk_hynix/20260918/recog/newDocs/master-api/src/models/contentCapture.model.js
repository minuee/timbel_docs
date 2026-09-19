import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class ContentCaptureModel extends BaseDatabase {
	constructor() {
		super('ContentCaptureModel');
	}

	async createContentCapture({
		captureType,
		captureAction,
		content,
		attendeeCount,
		creatorId,
		creatorNickName,
		shareEmail,
		serverId,
	}) {
		const { contentId, title, type: contentType, duration, meetingStartTime } = content;
		return await this.mariaDB.contentCapture.create({
			data: {
				captureType,
				captureAction,
				contentId,
				contentType,
				title,
				duration,
				meetingStartTime,
				attendeeCount,
				creatorId,
				creatorNickName,
				shareEmail,
				serverId,
			},
		});
	}

	async createManyContentCapture(contentCaptures) {
		return await this.mariaDB.contentCapture.createMany({
			data: contentCaptures,
		});
	}

	// 공유 현황 in, out 조회하기에 최적인 모델이라 사용..
	// query도 중복 실행하기 싫어서 raw 로 사용..
	// 나중에 업데이트 하는 방향으로..
	async getSharedCounts(email, memberId, { startDate, endDate }) {
		log.i(`[${email} ${memberId}] 공유 현황 조회 ${startDate} ~ ${endDate}`);
		const result = await this.mariaDB.$queryRaw`
        SELECT 
            COUNT(CASE WHEN shareEmail = ${email} THEN 1 END) as incomingCount,
            COUNT(CASE WHEN creatorId = ${memberId} THEN 1 END) as outgoingCount
        FROM ContentCapture
        WHERE createAt BETWEEN ${startDate} AND ${endDate}
        AND captureType = 'SHARE'
        AND captureAction = 'SHARED'
        AND (shareEmail = ${email} OR creatorId = ${memberId})
    `;

		const { incomingCount = 0, outgoingCount = 0 } = result[0] || {};

		return {
			incoming: Number(incomingCount),
			outgoing: Number(outgoingCount),
		};
	}
}

export default new ContentCaptureModel();
