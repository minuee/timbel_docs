import BaseDatabase from '@timbel-timblo-onpremise/prisma';

const defaultCreatorSelect = {
	user: {
		select: {
			profile: {
				select: {
					pid: true,
					nickName: true,
					email: true,
					thumbnailUrl: true,
				},
			},
		},
	},
};

const defaultContentSelect = {
	contentId: true,
	title: true,
	editedTitle: true,
	type: true,
	hashTag: true,
	manualTag: true,
	duration: true,
	transcribeStatus: true,
	meetingStartTime: true,
	creator: {
		select: defaultCreatorSelect,
	},
};

const defaultAttachedContentsSelect = {
	contentId: true,
	type: true,
	title: true,
	editedTitle: true,
	isRecord: true,
	fileName: true,
	shareUsers: {
		select: {
			email: true,
			role: true,
		},
	},
};

const defaultCalendarSelect = {
	id: true,
	meetingStartDate: true,
	provider: true,
	summary: true,
	title: true,
	reminderMinutes: true,
	content: {
		select: defaultContentSelect,
	},
	attachedContents: {
		select: defaultAttachedContentsSelect,
	},
};

const defaultIntegrateCalendarSelect = {
	id: true,
	provider: true,
	description: true,
	start: true,
	summary: true,
	isLoaded: true,
};

class CalendarModel extends BaseDatabase {
	constructor() {
		super('CalendarModel');
	}

	async getCalendarContents(pid, sharedContentIds, { contentFilter, type, startDate, endDate }) {
		const options = { orderBy: { createAt: 'asc' }, where: { AND: [] } };

		// 콘텐츠 필터 값 검증 및 기본값 설정
		const filterResolver = {
			all: { OR: [{ creatorPID: pid }, { contentId: { in: sharedContentIds } }], AND: [] },
			owned: { creatorPID: pid, AND: [] },
			sharedIn: { contentId: { in: sharedContentIds }, AND: [] },
			sharedOut: { creatorPID: pid, isShared: true, AND: [] },
		};
		options.where = filterResolver[contentFilter] || filterResolver.all;

		if (startDate && endDate) {
			options.where.AND.push({
				meetingStartTime: {
					gte: new Date(startDate.year, startDate.month, startDate.day),
					lte: new Date(endDate.year, endDate.month, endDate.day, 23, 59, 59, 999),
				},
			});
		}

		if (type) {
			options.where.AND.push({ type }); // contentType
		}

		const result = await this.mariaDB.contentWithUserProfiles.findMany(options);

		return result;
	}

	async getCalendars({ id, workspace }, options) {
		const { startDate, endDate } = options;

		const result = await this.mariaDB.calendar.findMany({
			select: defaultCalendarSelect,
			where: {
				AND: [
					{ creatorId: id },
					{ workspaceId: workspace.id },
					{ meetingStartDate: { gte: startDate, lte: endDate } },
				],
				OR: [
					{ contentId: null },
					{
						content: {
							isRecycle: false,
							isDeleted: false,
						},
					},
				],
			},
			orderBy: {
				meetingStartDate: 'desc',
			},
		});

		return result;
	}

	async createCalendar(member, createCalendarDTO) {
		const { provider = this.Enums.CalendarProvider.TIMBLO, attachedContents = [], ...rest } = createCalendarDTO;

		const { id: creatorId, workspace } = member;
		const { id: workspaceId } = workspace;
		const attachedContentsData = attachedContents.map(content => ({ contentId: content }));
		return await this.mariaDB.calendar.create({
			data: {
				...rest,
				provider,
				creator: { connect: { id: creatorId } },
				workspace: { connect: { id: workspaceId } },
				attachedContents: { connect: attachedContentsData },
			},
			select: defaultCalendarSelect,
		});
	}

	async upsertWebcal({ pid }, url, provider) {
		return await this.mariaDB.calendarIntegrate.upsert({
			where: { pid_provider: { pid, provider } },
			update: { url, lastSyncedAt: new Date() },
			create: { url, provider, pid, lastSyncedAt: new Date() },
		});
	}

	async getWebcales({ pid }) {
		return await this.mariaDB.calendarIntegrate.findMany({
			where: { pid },
			orderBy: { lastSyncedAt: 'desc' },
		});
	}

	async getLastSyncedWebcale({ pid }) {
		return await this.mariaDB.calendarIntegrate.findFirst({
			where: { pid, lastSyncedAt: { not: null } },
			orderBy: { lastSyncedAt: 'desc' },
		});
	}

	async disconnectWebcal({ pid }, provider) {
		return await this.mariaDB.calendarIntegrate.delete({
			where: { pid_provider: { pid, provider } },
		});
	}

	async upsertCalendarIntegrateSync(webcalDataArray, integrateId) {
		if (!webcalDataArray || webcalDataArray.length === 0) {
			return [];
		}

		const uids = webcalDataArray.map(data => data.uid);

		const existingSyncs = await this.mariaDB.calendarIntegrateSync.findMany({
			where: {
				integrateId,
				uid: { in: uids },
			},
			select: {
				uid: true,
			},
		});

		const existingUidSet = new Set(existingSyncs.map(sync => sync.uid));
		const toCreate = [];
		const toUpdate = [];

		webcalDataArray.forEach(data => {
			if (existingUidSet.has(data.uid)) {
				toUpdate.push(data);
			} else {
				toCreate.push({
					...data,
					integrateId,
				});
			}
		});

		// 배치 처리 크기
		const CREATE_BATCH_SIZE = 500;
		const UPDATE_BATCH_SIZE = 100;

		if (toCreate.length > 0) {
			log.i(`[CalendarModel] 생성할 항목: ${toCreate.length}개`);
			for (let i = 0; i < toCreate.length; i += CREATE_BATCH_SIZE) {
				const batch = toCreate.slice(i, i + CREATE_BATCH_SIZE);
				await this.mariaDB.calendarIntegrateSync.createMany({
					data: batch,
					skipDuplicates: true,
				});
			}
		}

		if (toUpdate.length > 0) {
			log.i(`[CalendarModel] 업데이트할 항목: ${toUpdate.length}개`);
			for (let i = 0; i < toUpdate.length; i += UPDATE_BATCH_SIZE) {
				const batch = toUpdate.slice(i, i + UPDATE_BATCH_SIZE);
				await this.mariaDB.$transaction(
					batch.map(data =>
						this.mariaDB.calendarIntegrateSync.update({
							where: { integrateId_uid: { integrateId, uid: data.uid } },
							data: { ...data },
							select: defaultIntegrateCalendarSelect,
						})
					),
					{
						timeout: 30000, // 30초
					}
				);
			}
		}

		const finalResults = await this.mariaDB.calendarIntegrateSync.findMany({
			where: {
				integrateId,
				uid: { in: uids },
			},
			select: defaultIntegrateCalendarSelect,
		});

		return finalResults;
	}

	async updateWebcalLastSyncedAt(webcales) {
		return await this.mariaDB.calendarIntegrate.updateMany({
			where: { id: { in: webcales.map(webcal => webcal.id) } },
			data: { lastSyncedAt: new Date() },
		});
	}

	async getIntegrateCalendars({ pid }) {
		return await this.mariaDB.calendarIntegrateSync.findMany({
			select: defaultIntegrateCalendarSelect,
			where: { integrate: { pid } },
			orderBy: { start: 'desc' },
		});
	}

	async getIntegrateCalendarsByIds(ids) {
		return await this.mariaDB.calendarIntegrateSync.findMany({
			where: { id: { in: ids } },
			select: {
				id: true,
				provider: true,
				description: true,
				start: true,
				summary: true,
			},
		});
	}

	async createIntegrateCalendar({ id, workspace }, integrateCalendarDTO) {
		return await this.mariaDB.$transaction(
			integrateCalendarDTO.map(data => {
				const calendarData = {
					title: data.summary,
					meetingStartDate: data.start,
					provider: data.provider,
					summary: data.description,
				};

				return this.mariaDB.calendar.upsert({
					where: { id: data.id },
					update: calendarData,
					create: { ...calendarData, creatorId: id, workspaceId: workspace.id },
				});
			})
		);
	}

	async updateIntegrateCalendarSync(ids, isLoaded = true) {
		return await this.mariaDB.calendarIntegrateSync.updateMany({
			where: { id: { in: ids } },
			data: { isLoaded },
		});
	}

	async getCalendarById(id) {
		return await this.mariaDB.calendar.findUnique({
			where: { id },
			select: defaultCalendarSelect,
		});
	}

	async deleteCalendar(id) {
		return await this.mariaDB.calendar.delete({
			where: { id },
		});
	}

	async updateCalendarReminderMinutes(id, reminderMinutes) {
		return await this.mariaDB.calendar.update({
			where: { id },
			data: { reminderMinutes },
			select: defaultCalendarSelect,
		});
	}
}

export default new CalendarModel();
