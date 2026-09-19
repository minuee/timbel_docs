import async from 'async';
import notify from '../notify.util.js';
import noteModel from '../../models/note.model.js';
import noteService from '../../services/content/features/note.service.js';
import contentCaptureService from '../../services/content/contentCapture.service.js';

const TAG = '[NoteQueueUtil] ';

class NoteQueueUtil {
	constructor(free, worker, concurrency) {
		this.queue = async.queue(this.updatingWorker.bind(this), 1);
		this.free = free;
	}

	// 노트 업데이트하는 queue worker
	async updatingWorker(taskParams) {
		try {
			let { action, user, noteId, updatingText, contentId, member } = taskParams;

			const latestNote = await noteService.getLatestNoteVersion(user, noteId);

			if (action === 'paste') {
				updatingText = latestNote?.content ? `${latestNote.content}${updatingText}` : updatingText;
			}

			const updatedNote = await noteModel.updateNoteContentTx(user, latestNote, updatingText);

			if (!updatedNote) {
				throw new HttpError(500, '노트 컨텐츠 업데이트 실패');
			}
			notify.updatingNoteContent({ status: 'SUCCESS' }, taskParams);

			await contentCaptureService.createContentCapture('CONTENT', 'UPDATE_NOTE', contentId, member.id, user);
		} catch (err) {
			notify.updatingNoteContent({ status: 'ERROR' }, taskParams);
			throw err;
		}
	}

	addTask(task) {
		try {
			const { noteId } = task;
			this.queue.push(task, err => {
				if (err) {
					log.e(TAG, `노트 수정 중 에러 발생! ${noteId} : ${err.message}`);
					throw err;
				}

				this.queue.drain().then(() => {
					this.cleanupQueue(task);
				});
			});
			log.i(TAG, `노트 큐, 작업 추가 noteId: ${noteId}`);
			log.i(TAG, `노트 큐, Status Waiting: ${this.queue.length()} | Running: ${this.queue.running()}`);
		} catch (err) {
			console.error('addTask err : ', err);
		}
	}

	cleanupQueue(task) {
		try {
			if (!this.queue) {
				log.e(TAG, '삭제할 큐가 존재하지 않습니다.');
				return;
			}

			if (this.queue.idle()) {
				delete this.queue;
				log.i(TAG, `노트의 모든 작업 완료! 큐 삭제 noteId: ${task.noteId}`);
				this.free(); // 인스턴스 생성시 설정한 noteTask 객체 키 삭제 함수 호출
			}
		} catch (err) {
			console.error('deleteQueue err : ', err);
		}
	}
}

export default NoteQueueUtil;
