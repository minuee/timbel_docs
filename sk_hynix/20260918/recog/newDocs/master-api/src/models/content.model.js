import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class ContentModel extends BaseDatabase {
	constructor() {
		super('ContentModel');
	}

	userProfileNickNameSelectOption = {
		select: {
			user: {
				select: {
					profile: {
						select: {
							nickName: true,
							pid: true,
						},
					},
				},
			},
		},
	};

	linkedContentSelectOption = {
		include: {
			linkedContent: {
				select: {
					contentId: true,
					editor: this.userProfileNickNameSelectOption,
					fileName: true,
					title: true,
					editedTitle: true,
					type: true,
					isRecycle: true,
					isDeleted: true,
					createAt: true,
					updateAt: true,
				},
			},
		},
	};

	// 내 소유 컨텐츠 조회
	async getMyOwnContentIds(pid, searchDTO) {
		const { folderId } = searchDTO;

		let where = {
			creator: { pid },
			createAt: { gte: searchDTO.startDate, lte: searchDTO.endDate },
		};

		if (folderId) {
			where.folderId = folderId;
		}

		return await this.mariaDB.content.findMany({
			where,
			select: { contentId: true },
		});
	}

	// 내가 접근 가능한 모든 콘텐츠 조회 (내가 생성한 것 + 공유받은 것) - 통합 쿼리
	async getMyAccessibleContentIds(pid, email, searchDTO) {
		const { mediaType, startDate, endDate } = searchDTO;
		const dateRange = { gte: startDate, lte: endDate };

		// 내가 생성한 것 OR 공유받은 것
		let where = {
			OR: [
				{ creator: { pid }, createAt: dateRange },
				{ shareUsers: { some: { email } }, createAt: dateRange },
			],
		};

		if (mediaType) where = { AND: [where, { type: mediaType }] };

		return await this.mariaDB.content.findMany({ where, select: { contentId: true } });
	}

	// 특정 콘텐츠 ID들에 대해 접근 가능한 콘텐츠만 조회 (내가 생성한 것 + 공유받은 것)
	async getAccessibleContentsByIds(contentIds, pid, email) {
		// 공유받은 콘텐츠 ID 조회
		const sharedContentIds = await this.getSharedContentIds(email);
		const sharedContentIdSet = new Set(sharedContentIds);

		// 요청된 콘텐츠 중에서 접근 가능한 것만 조회
		const accessibleContents = await this.mariaDB.contentWithUserProfiles.findMany({
			where: {
				contentId: { in: contentIds },
				OR: [
					{ creatorPID: pid }, // 내가 생성한 콘텐츠
					{ contentId: { in: sharedContentIds } }, // 공유받은 콘텐츠
				],
			},
		});

		return { accessibleContents, sharedContentIdSet };
	}

	async createContent(auth, data, manualOptions = {}, contentIds = []) {
		const { isMobile } = auth.config;
		const { id, workspace } = auth.member;
		const { id: workspaceId } = workspace;
		const {
			title,
			duration,
			inputType = 'AUDIO',
			isRecord,
			startTime,
			endTime,
			isParseDate,
			folderId = null,
		} = data;
		const defaultStatus = duration !== 0 ? 'WAITING' : 'ERROR';

		// Content 생성 (폴더 ID 포함)
		const content = await this.mariaDB.content.create({
			data: {
				title,
				isMobile,
				duration,
				hashTag: [],
				fileName: title,
				type: inputType,
				meetingEndTime: endTime,
				meetingStartTime: isParseDate ? startTime : undefined,
				editor: { connect: { id } },
				creator: { connect: { id } },
				transcribeStatus: defaultStatus,
				workspace: { connect: { id: workspaceId } },
				isRecord: isRecord || inputType.toUpperCase() === 'RECORD',
				folder: folderId ? { connect: { id: folderId } } : undefined,
				manualTag: manualOptions.tag,
				linkedContents: { createMany: { data: contentIds.map(contentId => ({ linkedContentId: contentId })) } },
			},
		});

		return content;
	}

	async createFileContent(contentId, data) {
		const { title, mimeType, duration, apiKey } = data;
		const defaultStatus = duration !== 0 ? 'WAITING' : 'ERROR';

		return await this.mongoDB.file.create({
			data: {
				duration,
				mimeType,
				fileName: title,
				fileKey: apiKey,
				contentId,
				sttStatus: defaultStatus,
			},
		});
	}

	async findFileByContentId(contentId, include = {}) {
		return await this.mongoDB.file.findFirst({
			where: {
				contentId,
			},
			include,
		});
	}

	async findContentCreatorByContentId(contentId) {
		return await this.mariaDB.contentWithUserProfiles.findUnique({
			where: {
				contentId,
			},
		});
	}

	async deleteFileContentByContentId({ fileId, contentId = null }) {
		if (!contentId) return false;
		await this.mariaDB.content.delete({
			where: {
				contentId,
			},
		});

		await this.mongoDB.file.delete({
			where: {
				id: fileId,
				contentId,
			},
		});

		return true;
	}

	async findContentById(contentId) {
		const content = await this.mariaDB.content.findUnique({
			where: {
				contentId,
			},
			include: {
				creator: this.userProfileNickNameSelectOption,
				editor: this.userProfileNickNameSelectOption,
				linkedContents: this.linkedContentSelectOption,
			},
		});
		if (!content) return content;

		const editorNickName = content.editor?.user.profile.nickName;
		const creatorNickName = content.creator.user.profile.nickName;
		const creatorPID = content.creator.user.profile.pid;

		content.lastUpdator = editorNickName || creatorNickName;
		content.creatorPID = creatorPID;
		return content;
	}

	async updateisRecycledContent(contentId) {
		return await this.mariaDB.content.update({
			where: {
				contentId,
			},
			data: {
				isRecycle: true,
			},
		});
	}

	async getTranscribeResultByContentId(contentId, selectFields = [], includeFields = []) {
		let select = {};

		if (selectFields && selectFields.length > 0) {
			selectFields.forEach(key => {
				select[key] = true;
			});
		}

		let include = {};
		if (includeFields && includeFields.length > 0) {
			includeFields.forEach(key => {
				include[key] = true;
			});
		}

		return await this.mongoDB.file.findFirst({
			where: { contentId },
			select: {
				transcribeResult: { select },
				...include,
			},
		});
	}

	/**
	 * @param {string} fileId
	 * @description 컨텐츠 상세 조회, 탭별 조회
	 */
	async getTranscribeResult(fileId, tabs) {
		const select = { status: true, clientLanguage: true, summarySize: true };

		if (tabs.length === 0) {
			select.aiResult = true;
			select.speakerInfo = true;
			select.summaryTime = true;
			select.segments = true;
			select.mergedSegments = true;
		} else {
			tabs.forEach(tab => {
				switch (tab) {
					case 'aiResult':
						select.aiResult = true;
						select.speakerInfo = true;
						break;
					case 'speakerInfo':
						select.speakerInfo = true;
						break;
					case 'summaryTime':
						select.summaryTime = true;
						break;
					case 'segments':
						select.mergedSegments = true;
						select.segments = true;
						break;
					default:
						break;
				}
			});
		}

		return await this.mongoDB.transcribeResult.findFirst({
			where: {
				fileId,
			},
			select: select,
		});
	}

	// 특정 컨텐츠 내 음성기록들만 조회
	async getSegments(fileId) {
		return await this.mongoDB.transcribeResult.findFirst({
			where: {
				fileId,
			},
			select: {
				mergedSegments: true,
			},
		});
	}

	// 특정 컨텐츠 내 음성기록들만 조회
	async getTranscription(contentId) {
		return await this.mongoDB.transcribeResult.findFirst({
			where: {
				contentId,
			},
			transcribeResult: {
				select: {
					segments: true,
					mergedSegments: true,
				},
			},
		});
	}

	async updateContent(where, data) {
		return this.mariaDB.content.update({
			where,
			data,
		});
	}

	async getSharedContentIds(email) {
		const sharedContentIds = await this.mariaDB.sharedUserProfile.findMany({
			where: {
				email,
			},
			select: {
				contentId: true,
			},
		});

		return sharedContentIds.reduce((acc, curr) => {
			acc.push(curr.contentId);
			return acc;
		}, []);
	}

	// 내가 생성한 콘텐츠 중 폴더에 속한 콘텐츠 ID들을 조회
	async getMyFolderContentIds(pid) {
		const contents = await this.mariaDB.content.findMany({
			where: {
				creator: { pid },
				folderId: { not: null },
			},
			select: {
				contentId: true,
			},
		});

		return contents.map(content => content.contentId);
	}

	// 공유받은 콘텐츠 중 폴더에 속한 콘텐츠 ID들을 조회
	async getSharedFolderContentIds(email) {
		const contents = await this.mariaDB.contentShareUser.findMany({
			where: {
				email,
				folderId: { not: null },
			},
			select: {
				contentId: true,
			},
		});

		return contents.map(content => content.contentId);
	}

	async getContents(pid, findOptions = {}) {
		const {
			take = 0,
			title = null,
			type = null,
			hashtags = null,
			owners = null,
			startDate = null,
			endDate = null,
			contentId = null,
			contentIds = null,
			sharedContentIds = [],
			contentFilter = this.Enums.ContentFilter.ALL,
			statusFilter = null,
			excludeFolder = false,
		} = findOptions;

		const options = { orderBy: { updateAt: 'desc' } };

		// 현재 조건문 구조상 contentIds와 contentFilter를 동시 적용 불가, 둘 중 하나만 적용
		if (contentIds && contentIds.length >= 0) {
			options.where = { contentId: { in: contentIds }, AND: [] };
		} else {
			// 콘텐츠 필터 값 검증 및 기본값 설정
			const filterResolver = {
				all: { OR: [{ creatorPID: pid }, { contentId: { in: sharedContentIds } }], AND: [] },
				owned: { creatorPID: pid, AND: [] },
				sharedIn: { contentId: { in: sharedContentIds }, AND: [] },
				sharedOut: { creatorPID: pid, isShared: true, AND: [] },
				// '내 회의록'(success) 병합용: (내 소유·완료·폴더미소속) ∪ (공유받은분).
				// DONE/folderId 조건은 소유 브랜치에만 걸리도록 OR 내부에 내장한다(전역 AND로 밀면 공유분까지 걸림).
				ownedOrSharedIn: {
					OR: [
						{ creatorPID: pid, transcribeStatus: 'DONE', folderId: null },
						{ contentId: { in: sharedContentIds } },
					],
					AND: [],
				},
			};
			options.where = filterResolver[contentFilter];
		}

		if (statusFilter) {
			switch (statusFilter.toUpperCase()) {
				case 'DONE':
					options.where.AND.push({ transcribeStatus: 'DONE' });
					break;
				case 'NOTERROR':
					options.where.AND.push({ transcribeStatus: { not: 'ERROR' } });
					break;
				case 'ERROR':
					options.where.AND.push({ transcribeStatus: 'ERROR' });
					break;
			}
		}

		// 실제 폴더에 속하지 않은 콘텐츠만 조회 (SUCCESS 가상폴더용)
		if (excludeFolder) {
			options.where.AND.push({ folderId: null });
		}

		if (title) {
			const OR = [{ title: { contains: title } }, { editedTitle: { contains: title, not: null, not: '' } }];
			options.where.AND.push({ OR });
		}

		if (type && type.toUpperCase() !== 'NULL') {
			const validContentTypes = new Set(Object.values(this.Enums.ContentType).map(t => t.toUpperCase()));
			const typeList = type
				.replaceAll(' ', '')
				.split(',')
				.filter(t => validContentTypes.has(t.trim().toUpperCase()));

			if (typeList.length) {
				options.where.AND.push({ type: { in: typeList } });
			}
		}

		if (hashtags) {
			const tagList = hashtags.split(',');

			if (tagList.length) {
				options.where.AND.push({ hashTag: { in: tagList } });
				options.where.AND.push({ manualTag: { in: tagList } });
			}
		}

		if (owners) {
			const ownerList = owners.split(',');

			if (ownerList.length) {
				options.where.AND.push({ creatorNickName: { in: ownerList } });
			}
		}

		if (take > 0) {
			options.take = take;
		}

		if (startDate && endDate) {
			options.where.createAt = {
				gte: startDate,
				lt: endDate,
			};
			log.i('[getContents] startDate:', startDate, 'endDate:', endDate);
		}

		if (contentId) {
			options.where.AND.push({ contentId: contentId });
		}

		return await this.mariaDB.contentWithUserProfiles.findMany(options);
	}

	async getBookmarkContents(email, { id }) {
		const sharedContents = await this.getSharedContentIds(email);
		return await this.mariaDB.content.findMany({
			where: {
				OR: [{ creatorId: id }, { contentId: { in: sharedContents } }],
				isRecycle: false,
				isDeleted: false,
				transcribeStatus: 'DONE',
			},
			orderBy: {
				updateAt: 'desc',
			},
			include: {
				creator: this.userProfileNickNameSelectOption,
				editor: this.userProfileNickNameSelectOption,
				shareUsers: {
					select: {
						contentId: true,
						email: true,
						role: true,
						createAt: true,
					},
				},
			},
		});
	}

	async getRecycleContents(creatorId, take, type) {
		const options = {
			orderBy: {
				updateAt: 'desc',
			},
			where: {
				creatorId,
				isRecycle: true,
				isDeleted: false,
			},
			include: {
				shareUsers: true,
				creator: {
					select: {
						user: {
							select: {
								pid: true,
							},
						},
					},
				},
			},
		};

		if (take > 0) {
			options.take = take;
		}

		if (type) {
			options.where = { type };
		}

		return await this.mariaDB.content.findMany(options);
	}

	// contentId만 조회하는 최적화된 함수 (폴더 유틸리티용)
	async getRecycleContentIds(creatorId) {
		return await this.mariaDB.content.findMany({
			where: {
				creatorId,
				isRecycle: true,
				isDeleted: false,
			},
			select: {
				contentId: true,
			},
		});
	}

	async isExistContent(contentId) {
		return await this.mariaDB.content.findUnique({
			where: { contentId },
		});
	}

	// 회의록을 휴지통으로 이동(deprecated)
	async moveContentToRecycleBin(contentId) {
		// Content의 isRecycle 상태만 업데이트 (folderId는 유지)
		return await this.mariaDB.content.update({
			where: { contentId },
			data: {
				isRecycle: true,
			},
		});
	}

	// 여러 회의록을 휴지통으로 동시 이동
	async moveBulkContentsToRecycleBin(contentIds) {
		// Content의 isRecycle 상태만 업데이트 (folderId는 유지)
		return await this.mariaDB.content.updateMany({
			where: { contentId: { in: contentIds } },
			data: { isRecycle: true },
		});
	}

	async restoreContent(contentId) {
		await this.mariaDB.content.update({
			where: { contentId },
			data: {
				isRecycle: false,
			},
		});

		return this.mariaDB.contentWithUserProfiles.findFirst({
			where: { contentId },
		});
	}

	async truncateContent(contentId) {
		return await this.mariaDB.content.update({
			where: { contentId },
			data: {
				isDeleted: true,
			},
		});
	}

	//휴지통 비우기
	async clearRecyleBin(creatorId) {
		return await this.mariaDB.content.updateMany({
			where: {
				creatorId,
				isRecycle: true,
				isDeleted: false,
			},
			data: {
				isDeleted: true,
			},
		});
	}

	async getThumbnails(contentIds) {
		return await this.mariaDB.sharedUserProfile.findMany({
			where: {
				contentId: { in: contentIds },
			},
		});
	}

	async updateTranscribeStatus(contentId, status) {
		return this.mariaDB.content.update({
			where: {
				contentId,
			},
			data: {
				transcribeStatus: status,
			},
		});
	}

	async updateContentTitle(contentId, title) {
		return this.mariaDB.content.update({
			where: {
				contentId,
			},
			data: {
				editedTitle: title,
			},
		});
	}

	async updateContentMeetingTime(contentId, meetingTime) {
		return this.mariaDB.content.update({
			where: {
				contentId,
			},
			data: meetingTime,
		});
	}

	async getMobileRecordContentByCreatorIdAndFileName(creatorId, fileName) {
		return await this.mariaDB.content.findFirst({
			where: {
				creatorId,
				fileName,
				isMobile: true,
				isRecord: true,
			},
		});
	}

	async findContentByCreatorIdAndTitle(creatorId, title) {
		return await this.mariaDB.content.findFirst({
			where: {
				creatorId,
				fileName: title,
				transcribeStatus: 'DONE',
				isRecycle: false,
				isDeleted: false,
			},
			orderBy: {
				updateAt: 'desc',
			},
		});
	}

	async updateMergedSegments(fileId, mergedSegments) {
		return await this.mongoDB.transcribeResult.update({
			where: {
				fileId,
			},
			data: {
				mergedSegments,
			},
		});
	}

	async getContentsByIds(contentIds) {
		return await this.mariaDB.contentWithUserProfiles.findMany({
			where: {
				contentId: {
					in: contentIds,
				},
			},
			orderBy: {
				updateAt: 'desc',
			},
		});
	}

	async findMyOwnContentsByIds(contentIds, pid) {
		return await this.mariaDB.contentWithUserProfiles.findMany({
			where: {
				creatorPID: pid,
				contentId: { in: contentIds },
			},
		});
	}

	async getContentsIncludeDeleteByIds(contentIds) {
		return await this.mariaDB.content.findMany({
			where: {
				contentId: {
					in: contentIds,
				},
			},
		});
	}

	async findSimpleContentById(contentId) {
		return await this.mariaDB.content.findUnique({
			where: {
				contentId,
			},
			select: {
				title: true,
				createAt: true,
				contentId: true,
			},
		});
	}

	async getContentDetail(contentId) {
		return await Promise.all([this.findContentById(contentId), this.getThumbnails([contentId])]);
	}

	async getUserContents(pid, { startDate, endDate }) {
		return await this.mariaDB.contentWithUserProfiles.findMany({
			where: {
				creatorPID: pid,
				transcribeStatus: 'DONE',
				createAt: {
					gte: startDate,
					lt: endDate,
				},
			},
			select: {
				contentId: true,
				duration: true,
				isRecord: true,
				createAt: true,
				updateAt: true,
			},
		});
	}

	async getUserContentsStats(pid, { startDate, endDate }) {
		const result = await this.mariaDB.$queryRaw`
			SELECT 
				COUNT(*) as total,
				COUNT(CASE WHEN isRecord = 1 THEN 1 END) as record,
				COUNT(CASE WHEN isRecord = 0 THEN 1 END) as upload,
				COALESCE(SUM(CASE WHEN isRecord = 1 THEN duration ELSE 0 END), 0) as recordDuration,
				COALESCE(SUM(CASE WHEN isRecord = 0 THEN duration ELSE 0 END), 0) as uploadDuration,
				DATE(createAt) as date,
				isRecord
			FROM ContentWithUserProfiles
			WHERE creatorPID = ${pid}
			AND transcribeStatus = 'DONE'
			AND createAt >= ${startDate}
			AND createAt < ${endDate}
			GROUP BY DATE(createAt), isRecord
			ORDER BY date ASC
		`;

		return result;
	}

	async getSharedContentCount(email, { startDate, endDate }) {
		return await this.mariaDB.contentShareUser.count({
			where: {
				email,
				createAt: {
					gte: startDate,
					lt: endDate,
				},
			},
		});
	}

	async findExpiredContentByWorkspaceId(policy, workspaceId, startDate = undefined) {
		const { value, unit } = policy;
		if (value < 1) return [];

		const now = new Date();
		let expirationDate;

		if (unit === 'DAYS') {
			expirationDate = new Date(now.getTime() - value * 24 * 60 * 60 * 1000);
		} else {
			throw new Error('지원하지 않는 단위입니다. DAYS를 사용해주세요.');
		}

		return await this.mariaDB.content.findMany({
			where: {
				workspaceId,
				createAt: { gte: startDate, lt: expirationDate },
			},
			select: {
				contentId: true,
				creatorId: true,
			},
		});
	}

	async findContentByIds(contentIds) {
		return await this.mariaDB.content.findMany({
			where: {
				contentId: { in: contentIds },
				isDeleted: false,
				isRecycle: false,
				isLocked: false,
			},
		});
	}

	async findContentHistoryByContentId(contentId) {
		return await this.mariaDB.content.findUnique({
			where: {
				contentId,
			},
			select: {
				type: true,
				title: true,
				meetingStartTime: true,
				meetingEndTime: true,
				duration: true,
				creator: {
					select: {
						workspaceId: true,
						user: {
							select: {
								profile: {
									select: {
										nickName: true,
										email: true,
									},
								},
							},
						},
					},
				},
			},
		});
	}

	async createTextContent(auth, data) {
		const { isMobile } = auth.config;
		const { id, workspace } = auth.member;
		const { id: workspaceId } = workspace;
		const { originalname, inputType, mimetype, apiKey } = data;
		const content = await this.mariaDB.content.create({
			data: {
				title: originalname,
				isMobile,
				hashTag: [],
				fileName: originalname,
				type: inputType,
				editor: { connect: { id } },
				creator: { connect: { id } },
				workspace: { connect: { id: workspaceId } },
				isRecord: false,
				folder: undefined,
				manualTag: [],
				transcribeStatus: 'WAITING',
			},
		});
		const file = await this.mongoDB.file.create({
			data: {
				duration: 0,
				mimeType: mimetype,
				fileName: originalname,
				fileKey: apiKey,
				contentId: content.contentId,
				sttStatus: 'WAITING',
			},
		});
		return { content, file };
	}
}

export default new ContentModel();
