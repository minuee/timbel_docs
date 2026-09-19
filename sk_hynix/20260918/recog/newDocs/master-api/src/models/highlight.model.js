import { HttpError } from '../handlers/error.handler.js';
import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class HighlightModel extends BaseDatabase {
	constructor() {
		super('HighlightModel');
	}

	async findHighlightByText(fileId, { category, text }, startIdx, endIdx) {
		try {
			const { key, idx, sub } = category;
			const whereOptions = {
				fileId,
				category: { equals: { key, idx: Number(idx), sub } },
				text: { contains: text },
				start: { equals: startIdx },
				end: { equals: endIdx },
			};
			log.i(`findHighlightByText: ${JSON.stringify(whereOptions)}`);
			return this.mongoDB.highlight.findFirst({
				where: whereOptions,
			});
		} catch (err) {
			console.log(err);
		}
	}

	async addHighlight(fileId, highlight) {
		return this.mongoDB.highlight.create({
			data: { file: { connect: { id: fileId } }, ...highlight },
		});
	}

	async deleteHighlight(fileId, ids = []) {
		if (!ids.length) return;
		return this.mongoDB.highlight.deleteMany({
			where: { fileId, id: { in: ids } },
		});
	}

	async findHighlightById(fileId, id) {
		try {
			const highlight = await this.mongoDB.highlight.findFirst({
				where: { fileId, id },
			});
			if (!highlight) throw new HttpError(1178);
			return highlight;
		} catch (err) {
			throw new HttpError(1178);
		}
	}

	async clearHighlightByFileId({ fileId }, key = null) {
		try {
			let whereOptions = { category: { isNot: { key: 'mergedSegments' } } };
			if (key === 'mergedSegments') whereOptions = { category: { is: { key: 'mergedSegments' } } };
			return this.mongoDB.highlight.deleteMany({
				where: {
					fileId,
					...whereOptions,
				},
			});
		} catch (err) {
			console.log(err);
		}
	}

	// 전사 영역의 특정 구간의 하이라이트만 삭제
	async clearHighlightBySegmentIndexes(fileId, indexes = []) {
		if (!indexes.length) return;
		return this.mongoDB.highlight.deleteMany({
			where: {
				fileId,
				category: {
					is: {
						key: 'mergedSegments',
						idx: { in: indexes },
					},
				},
			},
		});
	}
}

export default new HighlightModel();
