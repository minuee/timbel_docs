import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class TranscribeResultModel extends BaseDatabase {
	constructor() {
		super('FileModel');
	}

	async create(fileId, ticketId, auth) {
		const {
			config: { transcribeLang = this.Enums.SupportLang.ko },
			member: {
				workspace: {
					config: {
						transcribeEngine: { tag },
					},
				},
			},
		} = auth;
		await this.mongoDB.transcribeResult.create({
			data: {
				file: { connect: { id: fileId } },
				ticket: ticketId,
				status: 'WAITING',
				clientLanguage: transcribeLang,
				engine: tag,
			},
		});
	}

	// STT 재실행(재요약 STT 포함)용: fileId는 @unique(파일 1:1)라 create가 충돌하므로 upsert.
	// 기존 행이 있으면 ticket/status/engine을 리셋하고(세그먼트는 STT 완료 시 통째로 교체됨), 없으면 새로 생성.
	async upsert(fileId, ticketId, auth) {
		const {
			config: { transcribeLang = this.Enums.SupportLang.ko },
			member: {
				workspace: {
					config: {
						transcribeEngine: { tag },
					},
				},
			},
		} = auth;
		const data = {
			ticket: ticketId,
			status: 'WAITING',
			clientLanguage: transcribeLang,
			engine: tag,
		};
		await this.mongoDB.transcribeResult.upsert({
			where: { fileId },
			update: data,
			create: { file: { connect: { id: fileId } }, ...data },
		});
	}

	async updateStatus(where, data) {
		return this.mongoDB.transcribeResult.update({
			where,
			data,
		});
	}

	async findSpeakerInfoByContentId(contentId) {
		return this.mongoDB.file.findFirst({
			where: {
				contentId,
			},
			select: {
				contentId: true,
				transcribeResult: {
					select: {
						speakerInfo: true,
					},
				},
			},
		});
	}

	async findSpeakerInfosByContentIds(contentIds) {
		return this.mongoDB.file.findMany({
			where: {
				contentId: {
					in: contentIds,
				},
			},
			select: {
				contentId: true,
				transcribeResult: {
					select: {
						speakerInfo: true,
					},
				},
			},
		});
	}

	async findFileKeyByContentIds(contentIds) {
		const files = await this.mongoDB.file.findMany({
			where: {
				contentId: { in: contentIds },
			},
			select: {
				fileKey: true,
				contentId: true,
			},
		});
		return files;
	}

	async findSegmentByContentIds(contentIds) {
		return this.mongoDB.file.findMany({
			where: {
				contentId: { in: contentIds },
			},
			select: {
				contentId: true,
				transcribeResult: {
					select: {
						fileId: true,
						mergedSegments: true,
						segments: true,
					},
				},
			},
		});
	}

	async updateTranscribeResult(fileId, data) {
		return await this.mongoDB.transcribeResult.update({
			where: {
				fileId,
			},
			data,
		});
	}

	async createTextTranscribeResult(fileId, ticketId, auth, data = {}) {
		const {
			config: { transcribeLang = this.Enums.SupportLang.ko },
		} = auth;

		return await this.mongoDB.transcribeResult.create({
			data: {
				file: { connect: { id: fileId } },
				ticket: ticketId,
				status: 'TEXT_SPLIT_DONE',
				clientLanguage: transcribeLang,
				engine: 'TEXT_SPLITTER',
				segments: data.segments,
				mergedSegments: data.mergedSegments,
				speakerInfo: data.speakerInfo,
				aiResult: {
					manualTag: [],
				},
			},
		});
	}
}

export default new TranscribeResultModel();
