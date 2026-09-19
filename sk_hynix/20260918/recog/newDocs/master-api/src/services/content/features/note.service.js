import noteModel from '../../../models/note.model.js';
import noteQuque from '../../../utils/note/queue.util.js';
import notePaster from '../../../utils/note/paster.util.js';
import contentModel from '../../../models/content.model.js';
import templateModel from '../../../models/template.model.js';
import { HttpError } from '../../../handlers/error.handler.js';

class NoteService {
	constructor() {
		this.noteModel = noteModel;
		this.notePaster = notePaster;
		this.contentModel = contentModel;
		this.templateModel = templateModel;
		this.noteTasks = {};
	}

	// 노트 컨텐츠 가져오기
	async getNoteContent(contentId) {
		try {
			let note = await this.noteModel.getNoteContentByContentId(contentId);
			if (!note) note = await this.createFirstNote(contentId);

			return note;
		} catch (err) {
			throw err;
		}
	}

	// 나만의 노트 조회하기
	async getMyNoteContent({ pid }, contentId) {
		try {
			let myNote = await this.noteModel.getMyNoteContentByContentId(contentId, pid);
			if (!myNote) myNote = await this.createMyFirstNote(contentId, pid);

			return myNote;
		} catch (err) {
			throw err;
		}
	}

	// 첫 노트 생성(임시- 파일에 연결된 노트가 없어진 예외적인 상황)
	async createFirstNote(contentId, content = '') {
		try {
			const file = await this.contentModel.findFileByContentId(contentId);

			const note = await this.noteModel.createFirstNote(contentId, file.id, file.fileName, content);

			return note;
		} catch (err) {
			throw err;
		}
	}

	// 첫 나만의 노트 생성
	async createMyFirstNote(contentId, pid) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId);

			// +9시간 한 뒤, YY년 MM월 DD일 HH시mm분 형식으로 변환
			let datetime = new Date(Date.now() + 9 * 60 * 60 * 1000)
				.toISOString()
				.replace(/T|Z/g, ' ')
				.trim()
				.slice(2, 16);
			const noteData = { contentId, pid, noteName: `${datetime}에 생성된 내 노트`, content: '' };
			const note = await this.noteModel.createMyFirstNote(noteData, file.id);
			return note;
		} catch (err) {
			throw err;
		}
	}

	// 가장 최신 노트 버전 가져오기, 없으면 새로 생성
	async getLatestNoteVersion(user, noteId) {
		try {
			let [latestNote] = await this.noteModel.getLatestNoteVersion(noteId);

			if (!latestNote) {
				latestNote = await this.noteModel.createNewNoteVersion(user, noteId, 1, '');
			}

			return latestNote;
		} catch (err) {
			throw err;
		}
	}

	// 노트 수정
	async updateNoteContent(user, contentId, updatingText, { member }) {
		try {
			const note = await this.noteModel.getNoteContentByContentId(contentId);

			if (!note) throw new HttpError(404, '노트 컨텐츠가 존재하지 않습니다.');

			const taskParams = { action: 'update', user, noteId: note.id, updatingText, contentId, member };

			this.manageNoteQueueTask(taskParams);

			return;
		} catch (err) {
			throw err;
		}
	}

	// 나만의 노트 수정
	async updateMyNoteContent({ pid }, contentId, content) {
		try {
			const myNote = await this.noteModel.getMyNoteContentByContentId(contentId, pid);
			if (!myNote) throw new HttpError(404, '노트 컨텐츠가 존재하지 않습니다.');

			const result = await this.noteModel.updateMyNoteContentTx(myNote, content);

			return result;
		} catch (err) {
			throw err;
		}
	}

	// 노트 컨텐츠에 항목 붙여넣기
	async pasteTextIntoNote(user, contentId, itemKey, itemValue, { member }) {
		try {
			let note = await this.noteModel.getNoteContentByContentId(contentId);
			if (!note) note = await this.createFirstNote(contentId); // 노트가 없으면 생성

			const pastingNoteText = await this.notePaster.settingItemPastingIntoNote(itemKey, itemValue);

			const taskParams = {
				action: 'paste',
				user,
				noteId: note.id,
				updatingText: pastingNoteText,
				contentId,
				member,
			};

			this.manageNoteQueueTask(taskParams);

			return;
		} catch (err) {
			throw err;
		}
	}

	// 노트 처리 큐 관리
	manageNoteQueueTask(taskParams) {
		try {
			const { noteId } = taskParams;
			if (!this.noteTasks[noteId]?.queue) {
				//큐 생성하며, 큐가 비워질 때 실행될 함수 설정
				this.noteTasks[noteId] = new noteQuque(() => {
					delete this.noteTasks[noteId]; // 큐 작업 후 가장 마지막에 삭제
					log.i('[NoteService] ', `noteTasks 노트 객체 삭제 noteId: ${noteId}`);
				});
			}
			this.noteTasks[noteId].addTask(taskParams); // 만든 큐에 요청 건(taskPrarms)에 대한 작업 추가
		} catch (err) {
			throw err;
		}
	}

	// 노트 템플릿 목록 가져오기
	async getNoteTemplates(workspaceId) {
		try {
			// 모든 워크스페이스가 공용으로 사용하는 기본 템플릿 조회
			let globalTemplate = await this.templateModel.getGlobalTemplate();

			if (!globalTemplate) {
				await this.templateModel.createGlobalTemplate();
				globalTemplate = await this.templateModel.getGlobalTemplate();
			}

			// 워크스페이스별 템플릿 조회
			const workspaceTemplates = await this.templateModel.getNoteTemplates(workspaceId);

			return [globalTemplate, ...workspaceTemplates];
		} catch (err) {
			throw err;
		}
	}

	// 템플릿 상세 정보 가져오기
	async getTemplateDetail(templateId) {
		try {
			const template = await this.templateModel.getTemplateById(templateId);
			return template;
		} catch (err) {
			throw err;
		}
	}
}

export default new NoteService();
