import userModel from '../models/user.model.js';
import contentModel from '../models/content.model.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';

/**
 * 가상 폴더 관련 유틸리티 함수들
 */
class FolderUtil {
	// 가상 폴더 ID 상수
	VIRTUAL_FOLDER = {
		ROOT: 'root',
		RECEIVED: 'received',
		SUCCESS: 'success',
		ERROR: 'error',
		SENT: 'sent',
	};

	// 가상 폴더 관련 헬퍼 함수들
	getVirtualFolderIds() {
		return Object.values(this.VIRTUAL_FOLDER);
	}

	getVirtualFolderConfigs() {
		return [
			{ id: this.VIRTUAL_FOLDER.ROOT, name: '전체 회의록' },
			{ id: this.VIRTUAL_FOLDER.ERROR, name: '미완성 회의록' },
			{ id: this.VIRTUAL_FOLDER.SUCCESS, name: '내 회의록' },
			{ id: this.VIRTUAL_FOLDER.RECEIVED, name: '공유 받은 회의록' },
			{ id: this.VIRTUAL_FOLDER.SENT, name: '공유 한 회의록' },
		];
	}

	/**
	 * 가상 폴더 ID인지 확인
	 * @param {string} folderId - 확인할 폴더 ID
	 * @returns {boolean} 가상 폴더 여부
	 */
	isVirtualFolder(folderId) {
		return Object.values(this.VIRTUAL_FOLDER).includes(folderId);
	}

	/**
	 * 가상 폴더 ID에 따른 필터링 옵션 설정
	 * @param {string} folderId - 가상 폴더 ID
	 * @param {Object} searchDTO - 옵션 객체 (수정될 객체)
	 * @returns {Object} 설정된 옵션 객체
	 */
	applyVirtualFolderFilter(folderId, searchDTO, mergeSharedIntoMy = false) {
		if (!this.isVirtualFolder(folderId)) return searchDTO;

		if (folderId === this.VIRTUAL_FOLDER.ERROR) {
			searchDTO.contentFilter = Enums.ContentFilter.OWNED;
			searchDTO.statusFilter = 'ERROR';
		} else if (folderId === this.VIRTUAL_FOLDER.SUCCESS) {
			if (mergeSharedIntoMy) {
				// 워크스페이스 설정 ON: '내 회의록'에 공유받은 회의록 병합.
				// DONE/폴더미소속 조건은 content.model.js의 ownedOrSharedIn resolver OR 소유 브랜치에 내장됨.
				searchDTO.contentFilter = 'ownedOrSharedIn';
			} else {
				searchDTO.contentFilter = Enums.ContentFilter.OWNED;
				searchDTO.statusFilter = 'DONE';
				// 실제 폴더에 속하지 않은 콘텐츠만 조회 (folderId가 null인 것)
				searchDTO.excludeFolder = true;
			}
		} else if (folderId === this.VIRTUAL_FOLDER.RECEIVED) {
			searchDTO.contentFilter = Enums.ContentFilter.SHARED_IN;
		} else if (folderId === this.VIRTUAL_FOLDER.SENT) {
			searchDTO.contentFilter = Enums.ContentFilter.SHARED_OUT;
		} else if (folderId === this.VIRTUAL_FOLDER.ROOT) {
			searchDTO.contentFilter = Enums.ContentFilter.ALL;
		}

		return searchDTO;
	}

	/**
	 * 공유받은 콘텐츠 처리 (폴더에 속한 콘텐츠 제외)
	 * @param {string} pid - 사용자 PID
	 * @param {string} email - 사용자 이메일
	 * @param {Object} searchDTO - 옵션 객체 (수정될 객체)
	 * @returns {Promise<Object>} 처리된 옵션 객체
	 */
	async processSharedContentFilter(pid, email, searchDTO) {
		if (searchDTO.contentFilter === Enums.ContentFilter.SHARED_IN || searchDTO.contentFilter === 'ownedOrSharedIn') {
			const [myFolderContentIds, sharedFolderContentIds, sharedContentIds] = await Promise.all([
				contentModel.getMyFolderContentIds(pid),
				contentModel.getSharedFolderContentIds(email),
				contentModel.getSharedContentIds(email),
			]);

			// 폴더에 속한 콘텐츠들 제외 (내가 생성한 것 + 공유받은 것)
			const folderContentIdSet = new Set([...myFolderContentIds, ...sharedFolderContentIds]);
			const filteredSharedContentIds = sharedContentIds.filter(contentId => !folderContentIdSet.has(contentId));

			searchDTO.sharedContentIds = filteredSharedContentIds;
		}

		return searchDTO;
	}

	/**
	 * 폴더에 속한 contentIds 조회 (내가 생성한 콘텐츠 + 공유받은 콘텐츠)
	 * @param {string} pid - 사용자 PID
	 * @param {string} folderId - 폴더 ID
	 * @param {string} email - 사용자 이메일
	 * @returns {Promise<Array>} contentId 배열
	 */
	async getFolderContentIdsByFolderId(pid, folderId, email) {
		// 내가 생성한 콘텐츠와 공유받은 콘텐츠를 병렬로 조회
		const [myContentIds, sharedContentIds, recycleContentIds] = await Promise.all([
			userModel.getMyContentIdsByFolderId(folderId),
			userModel.getSharedContentIdsByFolderId(folderId, email),
			contentModel.getRecycleContentIds(pid),
		]);

		// Set을 미리 생성하여 성능 최적화
		const recycleContentIdSet = new Set(recycleContentIds.map(item => item.contentId));

		// map과 filter를 한 번에 처리하여 중간 배열 생성 최소화
		const allContentIds = [...myContentIds, ...sharedContentIds];
		const filteredContentIds = [];

		for (const item of allContentIds) {
			if (!recycleContentIdSet.has(item.contentId)) {
				filteredContentIds.push(item.contentId);
			}
		}

		return filteredContentIds;
	}

	/**
	 * 폴더 필터링 옵션 적용 (가상/실제 폴더 공통 처리)
	 * @param {string} pid - 사용자 PID
	 * @param {string} email - 사용자 이메일
	 * @param {string} folderId - 폴더 ID
	 * @param {Object} options - 옵션 객체
	 * @returns {Promise<Object>} 필터링된 옵션 객체
	 */
	async applyFolderFiltering(pid, email, folderId, options, mergeSharedIntoMy = false) {
		if (this.isVirtualFolder(folderId)) {
			// 가상 폴더는 필터링 옵션 적용
			let filteredOptions = this.applyVirtualFolderFilter(folderId, options, mergeSharedIntoMy);

			// 공유받은 콘텐츠 처리
			filteredOptions = await this.processSharedContentFilter(pid, email, filteredOptions);

			return filteredOptions;
		} else {
			// 실제 폴더는 contentIds로 처리
			const contentIds = await this.getFolderContentIdsByFolderId(pid, folderId, email);
			return { ...options, contentIds };
		}
	}
}

export default new FolderUtil();
