import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class ContactModel extends BaseDatabase {
	constructor() {
		super('ContactModel');
	}

	// 이메일로 주소록 조회
	async getUserByEmail(pid, email) {
		return await this.mariaDB.contact.findFirst({
			where: { pid, email },
		});
	}

	// 주소록 조회 필드 선택
	getSelectContactItem() {
		return {
			id: true,
			email: true,
			targetUser: { select: { pid: true, name: true, nickName: true, thumbnailUrl: true } },
			department: true,
			position: true,
			memo: true,
			isFavorite: true,
			isRecycle: true,
			createAt: true,
			updateAt: true,
			labels: {
				select: { label: { select: { id: true, name: true, color: true, createAt: true } } },
				orderBy: { label: { createAt: 'asc' } },
			},
		};
	}

	// 주소록 생성
	async createContact({ pid, email, memo, labelIds }) {
		return await this.mariaDB.contact.create({
			data: {
				pid,
				email,
				memo,
				labels: {
					create: labelIds.map(labelId => ({
						label: { connect: { id: labelId } },
					})),
				},
			},
			select: this.getSelectContactItem(),
		});
	}

	// 이메일 목록으로 기존 주소록 조회 (중복 체크용)
	async getContactsByEmails(pid, emails) {
		return await this.mariaDB.contact.findMany({
			where: { pid, email: { in: emails } },
			select: { email: true, isRecycle: true },
		});
	}

	// 주소록 일괄 생성 + 공통 라벨 연결 (트랜잭션)
	async createBulkContacts({ pid, usersToCreate, labelIds = [] }) {
		return await this.mariaDB.$transaction(async tx => {
			// 1. Contact 일괄 생성
			const contactsData = usersToCreate.map(user => ({
				pid,
				email: user.email,
				department: user.department,
				position: user.position,
				memo: user.memo,
			}));

			await tx.contact.createMany({ data: contactsData, skipDuplicates: true });

			// 2. 공통 라벨이 있는 경우 LabelOnContact 일괄 생성
			if (labelIds.length > 0) {
				// 생성된 Contact ID 조회
				const createdContacts = await tx.contact.findMany({
					where: {
						pid,
						email: { in: usersToCreate.map(u => u.email) },
					},
					select: { id: true },
				});

				// 모든 Contact에 공통 라벨 연결
				const labelOnContactData = createdContacts.flatMap(contact =>
					labelIds.map(labelId => ({
						contactId: contact.id,
						labelId: labelId,
					}))
				);

				await tx.labelOnContact.createMany({
					data: labelOnContactData,
					skipDuplicates: true,
				});
			}

			// 3. 최종 결과 조회 (전체 정보)
			const createdContacts = await tx.contact.findMany({
				where: {
					pid,
					email: { in: usersToCreate.map(u => u.email) },
				},
				select: this.getSelectContactItem(),
			});

			const _successCount = createdContacts.length;
			const _failedCount = usersToCreate.length - _successCount;
			return { _failedCount, _successCount, createdContacts };
		});
	}

	// 주소록 일괄 생성 + 행별 라벨 연결 (트랜잭션)
	async createBulkContactsWithLabels({ pid, usersToCreate, labelMap }) {
		return await this.mariaDB.$transaction(async tx => {
			// 각 사용자별로 Contact 생성 및 라벨 연결
			for (const user of usersToCreate) {
				// 1. Contact 생성
				const contact = await tx.contact.create({
					data: {
						pid,
						email: user.email,
						memo: user.memo || '',
					},
					select: { id: true, email: true },
				});

				// 2. 해당 행의 라벨 연결
				const labelIds = [];
				for (let i = 1; i <= 5; i++) {
					const labelName = user[`label${i}`];
					if (labelName && labelMap[labelName]) {
						labelIds.push(labelMap[labelName]);
					}
				}

				if (labelIds.length > 0) {
					const labelOnContactData = labelIds.map(labelId => ({
						contactId: contact.id,
						labelId,
					}));

					await tx.labelOnContact.createMany({
						data: labelOnContactData,
						skipDuplicates: true,
					});
				}
			}
		});
	}

	// 주소록 목록 조회(targetPids 전용)
	async getContactsByTargetPids(pid, targetPids) {
		return await this.mariaDB.contact.findMany({
			where: { pid, targetUser: { pid: { in: targetPids } } },
			select: this.getSelectContactItem(),
			orderBy: { targetUser: { nickName: 'asc' } },
		});
	}

	// 주소록 찾기
	async findContactById(pid, contactId) {
		return await this.mariaDB.contact.findUnique({
			where: { pid, id: contactId },
		});
	}

	// 주소록 삭제(deprecated)
	async deleteContact(contactId) {
		return await this.mariaDB.contact.delete({
			where: { id: contactId },
		});
	}

	// 주소록 다중 삭제
	async deleteContacts(contactIds) {
		return await this.mariaDB.contact.deleteMany({
			where: { id: { in: contactIds } },
		});
	}

	// 주소록 수정
	async updateContact(contactId, { memo, labelIds }) {
		return await this.mariaDB.$transaction(async prisma => {
			// 1. 주소록 정보 업데이트 (memo가 전달된 경우만)
			if (memo !== undefined) {
				await prisma.contact.update({ where: { id: contactId }, data: { memo } });
			}

			// 2. 라벨 업데이트 (labelIds가 전달된 경우만)
			if (labelIds !== undefined) {
				// 기존 라벨 연결 모두 제거
				await prisma.labelOnContact.deleteMany({ where: { contactId } });

				// 새로운 라벨들 연결
				if (labelIds.length > 0) {
					await prisma.labelOnContact.createMany({
						data: labelIds.map(labelId => ({ contactId, labelId })),
					});
				}
			}

			// 3. 최종 결과 조회 (라벨 포함)
			const finalContact = await prisma.contact.findUnique({
				where: { id: contactId },
				select: this.getSelectContactItem(),
			});

			return finalContact;
		});
	}

	// 주소록 존재 여부 체크
	async findContactByIds(pid, contactIds) {
		return await this.mariaDB.contact.findMany({
			where: { pid, id: { in: contactIds } },
			select: { id: true, pid: true, isFavorite: true, isRecycle: true },
		});
	}

	// 주소록 즐겨찾기 수정
	async updateContactFavorite(contactIds, isFavorite) {
		await this.mariaDB.contact.updateMany({
			where: { id: { in: contactIds } },
			data: { isFavorite },
		});
	}

	// 주소록 휴지통 이동 수정
	async updateContactRecycle(contactIds, isRecycle) {
		await this.mariaDB.contact.updateMany({
			where: { id: { in: contactIds } },
			data: { isRecycle },
		});
	}

	// 여러 주소록에 라벨 업데이트 (기존 라벨 제거 후 새로운 라벨 연결)
	async updateContactLabelsBatch(contactIds, labelIds) {
		// 트랜잭션으로 기존 라벨 제거 후 새로운 라벨 연결
		await this.mariaDB.$transaction(async prisma => {
			// 기존 라벨 연결 모두 제거
			await prisma.labelOnContact.deleteMany({
				where: { contactId: { in: contactIds } },
			});

			// 새로운 라벨들 연결
			if (labelIds.length > 0 && contactIds.length > 0) {
				const data = contactIds.flatMap(contactId =>
					labelIds.map(labelId => ({
						contactId,
						labelId,
					}))
				);
				await prisma.labelOnContact.createMany({
					data,
				});
			}
		});
	}

	// 주소록 목록 조회 및 검색 공통 쿼리 빌더 메서드(정렬 옵션을 위한 처리)
	async buildContactQuery(pid, options = {}) {
		const { page, take, sort, direction, keyword, isFavorite, isRecycle, labelId } = options;

		// 기본 쿼리 구성
		const query = {
			where: { pid },
			select: this.getSelectContactItem(),
		};

		// 정렬 처리
		query.orderBy = sort !== 'nickName' ? { [sort]: direction } : { targetUser: { [sort]: direction } };

		// 검색 키워드가 있는 경우 검색 조건 추가
		if (keyword) query.where.OR = this.searchWhere(keyword);

		// take=0이면 전체 조회, 혹은 페이지네이션 처리
		if (take > 0 && page) {
			query.take = take;
			query.skip = (page - 1) * take;
		}

		if (typeof isFavorite === 'boolean') query.where.isFavorite = isFavorite;
		if (typeof isRecycle === 'boolean') query.where.isRecycle = isRecycle;
		if (labelId) query.where.labels = { some: { labelId } };

		return query;
	}

	// 검색 조건 추가
	searchWhere(keyword) {
		return [
			{ targetUser: { name: { contains: keyword } } },
			{ targetUser: { nickName: { contains: keyword } } },
			{ email: { contains: keyword } },
			{ department: { contains: keyword } },
		];
	}

	// 주소록 목록 조회
	async getContactsAndCount(pid, options = {}) {
		const query = await this.buildContactQuery(pid, options);
		const [contacts, _count] = await Promise.all([
			this.mariaDB.contact.findMany(query),
			this.mariaDB.contact.count({ where: query.where }),
		]);
		return { contacts, _count };
	}

	// 주소록 검색
	async searchContacts(pid, options = {}) {
		const query = await this.buildContactQuery(pid, options);
		return await this.mariaDB.contact.findMany(query);
	}

	async getContactCount(pid, { startDate, endDate }) {
		const [periodCount, totalCount] = await Promise.all([
			this.mariaDB.contact.count({
				where: {
					pid,
					createAt: {
						gte: startDate,
						lt: endDate,
					},
				},
			}),
			this.mariaDB.contact.count({
				where: {
					pid,
				},
			}),
		]);

		return {
			periodCount,
			totalCount,
		};
	}
}
export default new ContactModel();
