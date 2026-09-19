import generate from '../utils/generate.util.js';
import userModel from '../models/user.model.js';
import notify from '@timbel-timblo-onpremise/notify';
import contentModel from '../models/content.model.js';
import convert from './convert/index.js';
import contentDetailService from '../services/content/contentDetail.service.js';

const TAG = '[Notify] ';
await notify.connect();
class Notify {
	async sttStatus({ status = 'ERROR', percentage, type = 'STT_STATUS' }, task, { id }) {
		const { contentId, fileId, ticketId, fileName } = task;
		const pushMsg = {
			type,
			channel: 'event',
			action: 'CONTENTS_CHANGED',
			majorType: 'CONTENTS_CHANGED',
			data: {
				status,
				fileId,
				ticketId,
				contentId,
				fileName,
				percentage,
			},
			time: new Date(),
		};

		notify.personal(
			`member:${id}`,
			{
				web: pushMsg,
				mobile: { key: 'mobile', ...pushMsg },
			},
			{ expire: { now: 1 } }
		);

		return await generate.delayWithRandom(`notify-${status}`);
	}

	generateSamlUrl(external = {}, contentId) {
		if (!process.env.SSO_SAML_URL) return `${process.env.HOME_URL}content/${contentId}`;

		const externalKeys = Object.keys(external);
		let SSO_SAML_URL = process.env.SSO_SAML_URL;
		for (const key of externalKeys) {
			SSO_SAML_URL = SSO_SAML_URL.replace(`##${key.toUpperCase()}##`, external[key]);
		}
		return `${SSO_SAML_URL}${process.env.HOME_URL}api/auth/sso?meeting_id=${contentId}`;
	}

	async externalEvent({ status = 'ERROR', external, err = {} }, task) {
		if (!external) return;
		const { contentId, ticketId, user } = task;
		const { company = undefined } = user;
		const content = await contentModel.findSimpleContentById(contentId);
		const contentDetail =
			status === 'DONE' ? await contentDetailService(user, contentId, { source: '', tabs: [] }) : {};
		const url = this.generateSamlUrl(external, contentId);
		const pushMsg = {
			external,
			type: 'EXTERNAL_EVENT',
			data: {
				url,
				status,
				content,
				company,
				ticketId,
				contentId,
				err: err instanceof Error ? { message: err.message } : err,
				contentDetail,
			},
		};

		notify.web.personal(`external:${external.token}`, pushMsg, {
			expire: { now: 1 },
		});
	}

	async inviteEmail(targetEmail, contentId, user) {
		const { email, nickName } = user;
		const content = await contentModel.findContentById(contentId);
		const { HOME_URL } = process.env;
		const inviteLink = `${HOME_URL}join?email=${targetEmail}`;

		log.i(TAG, `inviteEmail Send`);
		const payload = {
			data: {
				email,
				inviteLink,
				creator: nickName,
				contentName: content.title,
			},
			channel: 'email',
			title: `[AI회의록 공유] ${nickName}(${email})님이 '${content.title}' 회의록을 공유하셨습니다.`,
			type: 'INVITE',
		};

		notify.web.personal(targetEmail, payload);
	}

	async sharedContent(from, targetEmail, contentId, isMobile) {
		const { email, nickName } = from;
		const content = await contentModel.findContentById(contentId);
		const { HOME_URL } = process.env;
		const contentLink = `${HOME_URL}content/${contentId}`;

		log.i(TAG, `sharedContent Send`);

		const payload = {
			data: {
				email,
				contentLink,
				creator: nickName,
				contentName: content.title,
			},
			channel: 'email',
			title: `[AI회의록 공유] ${nickName}(${email})님이 '${content.title}' 회의록을 공유하셨습니다.`,
			type: 'SHARE',
			permissionInfo: {
				contentId,
				isMobile,
			},
		};

		notify.web.personal(targetEmail, payload);
		this.sharedContentEvent(contentId, [targetEmail]);
	}

	async contentDoneEmail(contentId, isCreate = true, user, isMobile, isMerge = false, workspaceId = null) {
		const { email } = user;
		const content = await contentModel.findContentById(contentId);
		const { HOME_URL } = process.env;
		const contentLink = `${HOME_URL}content/${contentId}`;

		log.i(TAG, `contentDoneEmail Send`);

		const data = {
			contentLink,
			contentName: content.title,
			type_1:
				isCreate ? '생성'
				: isMerge ? '합지기'
				: '재요약',
			type_2: isCreate ? '생성' : '새롭게 요약',
		};

		// 워크스페이스 기능권한(email_content_summary) On이면 상세 요약(회의록 상세화면의 '템플릿 상세 요약'
		// = transcribeResult.aiResult.templateSummary)을 이메일 본문에 첨부한다. Off면 현행(링크만).
		const includeSummary = await userModel.getWorkspaceBooleanSetting(workspaceId, 'email_content_summary');
		if (includeSummary) {
			const transcribe = await contentModel.getTranscribeResultByContentId(contentId, ['aiResult']);
			const templateSummary = transcribe?.transcribeResult?.aiResult?.templateSummary || '';
			// 마크다운 → 이메일용 스타일 HTML (캘린더 리마인드와 동일 변환 파이프라인)
			if (templateSummary) data.summary = convert.convertSummaryToHtml(templateSummary);
		}
		log.i(
			TAG,
			`[email-summary] contentId=${contentId} workspaceId=${workspaceId} toggle=${includeSummary} attachedLen=${data.summary ? data.summary.length : 0}`
		);

		const payload = {
			data,
			channel: 'email',
			title:
				isCreate ? `[AI회의록 생성] '${content.title}' 회의록이 생성되었습니다.`
				: isMerge ? `[AI회의록 합치기] '${content.title}' 회의록이 합치기 되었습니다.`
				: `[AI회의록 재요약] '${content.title}' 회의록이 재요약되었습니다.`,
			type: 'CONTENT',
			permissionInfo: {
				contentId,
				isMobile,
			},
		};

		notify.web.personal(email, payload);
	}

	updatingNoteContent({ status }, { noteId, user, contentId, updatingText }) {
		// 노트 작업자들에게만 알림을 보내면 소켓 연결된 사람을 찾아서 보냄
		// 해당 컨텐츠를 공유한 모든 사용자에게 알림을 보내는지 확인 필요
		log.i(TAG, `updatingNoteContent Send`);
		const payload = {
			type: 'NOTE_UPDATED',
			channel: 'collaboration',
			action: 'NOTE_UPDATED',
			majorType: 'NOTE_UPDATED',
			data: {
				noteId,
				status: status,
				lastUpdateUser: user,
				contentId,
				updatingText,
			},
		};

		notify.web.personal(contentId, payload);
	}

	async updatingContentPermission(permission, contentId, emails) {
		const users = await userModel.findUserProfileByEmails(emails);

		log.i(TAG, `updatingContentPermission Send ${emails.length} users`);
		const notifies = users.map(user => {
			return {
				userKey: user.pid,
				message: {
					type: 'PERMISSION_UPDATED',
					channel: 'event',
					action: 'PERMISSION_UPDATED',
					majorType: 'PERMISSION_UPDATED',
					data: {
						pid: user.pid,
						email: user.email,
						contentId,
						permission,
					},
				},
			};
		});
		return notify.web.personals(notifies);
	}
	async sharedContentEvent(contentId, emails, isAdded = true) {
		const users = await userModel.findUserProfileByEmails(emails);
		log.i(TAG, `sharedContentEvent Send ${emails.length} users`);
		const notifies = users.map(user => {
			return {
				userKey: user.pid,
				message: {
					type: 'SHARE_CONTENT',
					channel: 'event',
					action: 'SHARE_CONTENT',
					isAdded,
					data: {
						pid: user.pid,
						email: user.email,
						contentId,
					},
				},
			};
		});
		return notify.web.personals(notifies);
	}

	async reminderEmail({ email }, payload) {
		log.i(TAG, `reminderEmail Send to ${email} : ${JSON.stringify(payload)}`);
		notify.web.personal(email, payload);
	}

	async recycleContentEvent(user, contents) {
		const { email } = user;
		log.i(TAG, `recycleContentEvent Send to ${email} : ${JSON.stringify(contents)}`);
		const contentTitle = contents[0].editedTitle || contents[0].title;
		const deletedCount = contents.length;
		const payload = {
			data: {
				contentName: deletedCount > 1 ? `${contentTitle} 외 ${deletedCount - 1}개` : contentTitle,
			},
			channel: 'email',
			title:
				deletedCount > 1 ?
					`[AI회의록 삭제] '${contentTitle}' 외 ${deletedCount - 1}개 회의록이 삭제되었습니다.`
				:	`[AI회의록 삭제] '${contentTitle}' 회의록이 삭제되었습니다.`,
			type: 'RECYCLE',
		};
		notify.web.personal(email, payload);
	}
}

export default new Notify();
