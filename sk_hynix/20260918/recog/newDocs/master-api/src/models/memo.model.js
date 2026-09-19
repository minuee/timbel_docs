import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class MemoModel extends BaseDatabase {
	constructor() {
		super('MemoModel');
	}

	async findItemInfo(fileId, item, itemId) {
		let where = { fileId };

		if (item === 'summaryTime') where.summaryTime = { some: { index: itemId } };
		else if (item === 'segments' || item === 'mergedSegments') where.segments = { some: { segmentId: itemId } };

		return await this.mongoDB.transcribeResult.findFirst({
			where,
			select: {
				segments: true,
				summaryTime: true,
				mergedSegments: true,
			},
		});
	}

	async getMemosByContentId(contentId) {
		const userProfileNickNameSelectOption = {
			select: {
				user: {
					select: {
						profile: {
							select: {
								pid: true,
								name: true,
								nickName: true,
							},
						},
					},
				},
			},
		};

		return await this.mariaDB.memo.findMany({
			where: {
				contentId,
			},
			select: {
				id: true,
				item: true,
				itemId: true,
				startTime: true,
				text: true,
				isSecret: true,
				creator: userProfileNickNameSelectOption,
				createAt: true,
				updateAt: true,
				deleteAt: true,
				comments: {
					select: {
						id: true,
						text: true,
						creator: userProfileNickNameSelectOption,
						createAt: true,
						updateAt: true,
						deleteAt: true,
					},
					orderBy: {
						createAt: 'asc',
					},
				},
			},
			orderBy: {
				createAt: 'asc',
			},
		});
	}

	async getMemo(id) {
		return await this.mariaDB.memo.findFirst({
			where: {
				id,
			},
			include: {
				comments: true,
			},
		});
	}

	async getContentMemosByCreator(contentId, creatorId) {
		return await this.mariaDB.memo.findMany({
			where: {
				contentId,
				creatorId,
			},
		});
	}

	async createMemo(data) {
		return await this.mariaDB.memo.create({
			data,
		});
	}

	async updateMemo(id, updateMemoDTO) {
		const { text = null, isSecret = null } = updateMemoDTO;
		const data = {};
		if (text) data.text = text;
		if (isSecret !== null) data.isSecret = isSecret;

		return await this.mariaDB.memo.update({
			where: {
				id,
			},
			data,
		});
	}

	async updateMemosSecret(contentId, isSecret) {
		return await this.mariaDB.memo.updateMany({
			where: {
				contentId,
				isSecret: !isSecret,
			},
			data: {
				isSecret,
			},
		});
	}

	async softDeleteMemo(ids) {
		return await this.mariaDB.memo.updateMany({
			where: {
				id: { in: ids },
			},
			data: {
				text: null,
				deleteAt: new Date(),
			},
		});
	}

	async getMemoComment(id) {
		return await this.mariaDB.memo.findFirst({
			where: {
				id,
			},
			include: {
				comments: true,
			},
		});
	}

	async createMemoComment(data) {
		return await this.mariaDB.memoComment.create({
			data,
		});
	}

	async updateMemoComment(id, data) {
		return await this.mariaDB.memoComment.update({
			where: {
				id,
			},
			data,
		});
	}

	async softDeleteMemoComment(id) {
		return await this.mariaDB.memoComment.update({
			where: {
				id,
			},
			data: {
				text: null,
				deleteAt: new Date(),
			},
		});
	}

	async realDeleteMemosByContentId(contentId) {
		return await this.mariaDB.memo.deleteMany({
			where: {
				contentId,
			},
		});
	}
}

export default new MemoModel();
