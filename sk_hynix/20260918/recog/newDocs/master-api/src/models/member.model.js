import { HttpError } from '../handlers/error.handler.js';
import BaseDatabase from '@timbel-timblo-onpremise/prisma';

export class MemberModel extends BaseDatabase {
	constructor() {
		super('MemberModel');
	}

	async findMemberByPID(pid, select) {
		if (!pid) throw new HttpError(1201);
		const result = await this.mariaDB.member.findFirst({
			select,
			where: {
				user: { pid },
			},
		});

		if (result === null) throw new HttpError(1201);

		return result;
	}

	async findMemberContentByIdAndCreatorId(contentId, memberId, email) {
		return await this.mariaDB.content.findFirst({
			where: {
				OR: [
					{ creatorId: memberId, contentId },
					{ shareUsers: { some: { email: email } }, contentId },
				],
			},
			select: {
				contentId: true,
				title: true,
				creatorId: true,
				workspaceId: true,
				shareUsers: {
					where: { email: email },
					select: {
						email: true,
						role: true,
					},
				},
			},
		});
	}

	async getMembersFromWorkspace(workspaceId) {
		return await this.mariaDB.member.findMany({
			where: {
				workspaceId,
			},
			select: {
				pid: true,
			},
		});
	}

	async getMemberByPid(pid) {
		return await this.mariaDB.member.findFirst({
			where: { pid },
			select: {
				id: true,
				pid: true,
				user: {
					select: {
						profile: {
							select: {
								email: true,
							},
						},
					},
				},
			},
		});
	}

	async findMemberByUserEmail(email) {
		return await this.mariaDB.member.findFirst({
			where: {
				user: {
					profile: {
						email,
					},
				},
			},
		});
	}
}

export default new MemberModel();
