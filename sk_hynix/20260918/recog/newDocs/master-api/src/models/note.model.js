import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class NoteModel extends BaseDatabase {
	constructor() {
		super('NoteModel');
	}

	/**
	 * @param {string} contentId
	 * @description 컨텐츠별 노트 조회
	 */
	async getNoteContentByContentId(contentId) {
		try {
			return await this.mongoDB.note.findFirst({
				where: {
					contentId,
				},
				select: {
					id: true,
					content: true,
					revisions: {
						select: {
							id: true,
							version: true,
						},
						orderBy: {
							version: 'desc',
						},
						take: 1,
					},
				},
			});
		} catch (err) {
			throw err;
		}
	}

	// 컨텐츠별 나만의 노트 조회
	async getMyNoteContentByContentId(contentId, pid) {
		return await this.mongoDB.note.findFirst({
			where: {
				contentId,
				pid,
			},
			select: {
				id: true,
				content: true,
				revisions: {
					select: {
						id: true,
						version: true,
					},
					orderBy: {
						version: 'desc',
					},
					take: 1,
				},
			},
		});
	}

	/**
	 * @param {string} contentId
	 * @param {string} content
	 * @description (임시, 노트가 삭제된 예외 상황)노트 컨텐츠 신규 생성, 기존 파일에 노트 링크
	 */
	async createFirstNote(contentId, fileId, fileName = '', content = '') {
		// 트랜잭션
		return await this.mongoDB.$transaction(async tx => {
			const newNote = await tx.note.create({
				data: {
					contentId,
					noteName: `${fileName}_note`,
					content,
				},
			});

			const file = await tx.file.update({
				where: {
					id: fileId,
				},
				data: {
					linkNoteId: newNote.id,
				},
			});

			return newNote;
		});
	}

	/**
	 * @description 내 노트 컨텐츠 신규 생성, 기존 파일에 노트 링크
	 */
	async createMyFirstNote(myNoteData, fileId) {
		return await this.mongoDB.$transaction(async tx => {
			const newNote = await tx.note.create({
				data: {
					...myNoteData,
					revisions: {
						create: {
							version: 0,
							content: myNoteData.content,
						},
					},
				},
				select: {
					id: true,
					content: true,
					revisions: {
						select: {
							id: true,
							version: true,
						},
						orderBy: {
							version: 'desc',
						},
						take: 1,
					},
				},
			});

			await tx.file.update({
				where: {
					id: fileId,
				},
				data: {
					linkNoteId: newNote.id,
				},
			});

			return newNote;
		});
	}

	// 가장 최신 노트 버전 가져오기
	async getLatestNoteVersion(noteId) {
		return await this.mongoDB.noteRevision.findMany({
			where: {
				noteId,
			},
			select: {
				id: true,
				noteId: true,
				version: true,
				content: true,
				lastUpdateUser: true,
			},
			orderBy: {
				version: 'desc',
			},
			take: 1,
		});
	}

	// 새로운 노트 버전 생성
	async createNewNoteVersion({ pid }, noteId, version, noteContent) {
		return await this.mongoDB.noteRevision.create({
			data: {
				lastUpdateUser: pid,
				noteId,
				version,
				content: noteContent,
			},
		});
	}

	// 노트 컨텐츠 업데이트 트랜잭션
	async updateNoteContentTx({ pid }, latestNote, updatingContent) {
		const { id: versionId, noteId, version: latestVersion } = latestNote;

		return await this.mongoDB.$transaction(async tx => {
			let updatedNoteContent = await tx.note.update({
				where: {
					id: noteId,
				},
				data: {
					content: updatingContent,
				},
				select: {
					id: true,
					content: true,
					createAt: true,
					updateAt: true,
				},
			});

			/**
			 * 버전 자체가 없을 때 사용자 요청시,
			 * 앞서 서비스에서 version 1을 ''으로 생성했으니, 그냥 버전1을 업데이트 처리
			 */
			await tx.noteRevision.upsert({
				where: {
					id: versionId,
					version: 1,
					content: '',
				},
				create: {
					lastUpdateUser: pid,
					noteId,
					version: latestVersion + 1,
					content: updatingContent,
				},
				update: {
					content: updatingContent,
				},
			});

			return updatedNoteContent;
		});
	}

	// 나만의 노트 컨텐츠 업데이트 트랜잭션
	async updateMyNoteContentTx(note, content) {
		const { id: noteId, revisions, noteName } = note;
		return await this.mongoDB.$transaction(async tx => {
			await tx.noteRevision.create({
				data: {
					noteName,
					content,
					note: { connect: { id: noteId } },
					version: revisions[0].version + 1,
				},
			});

			const updatedMyNoteContent = await tx.note.update({
				where: { id: noteId },
				data: { noteName, content },
				select: {
					id: true,
					content: true,
					revisions: {
						select: {
							id: true,
							version: true,
						},
						orderBy: {
							version: 'desc',
						},
						take: 1,
					},
				},
			});

			return updatedMyNoteContent;
		});
	}

	// 노트 붙여넣기 -> mergedSegments 에서 참석자 조회
	async getSpeakerInfo(segmentId) {
		return await this.mongoDB.transcribeResult.findFirst({
			where: { mergedSegments: { some: { segmentId } } },
			select: { speakerInfo: true },
		});
	}
}

export default new NoteModel();
