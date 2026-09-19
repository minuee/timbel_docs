import contentService from '../content/content.service.js';
import searchModel from '../../models/search.model.js';
import bookmarkModel from '../../models/bookmark.model.js';
import calendarService, { getContentsResponseWithIds } from '../feature/calendar.service.js';
import { userService } from '../index.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';
import { getSearchRange } from '../../utils/date.util.js';
import usageUtil from '../../utils/usage.util.js';
import BaseService from '../base.service.js';

/**
 * Dashboard Service
 * 대시보드 위젯에 필요한 모든 데이터를 통합 제공
 */
class DashboardService extends BaseService {
	constructor() {
		super();
	}

	/**
	 * 대시보드용 통합 데이터 조회
	 * - todayMeetings: 오늘의 회의 일정
	 * - recentContents: 최근 콘텐츠 목록
	 * - monthlySummary: 월간 사용량 요약
	 * - bookmarks: 북마크 목록
	 * - keywords: 검색 키워드 히스토리
	 */
	async getDashboardData(user, auth) {
		const { pid, email } = user;
		const { member } = auth;

		// 오늘 날짜 범위 계산 (00:00:00 ~ 23:59:59)
		const today = new Date();
		const startOfDay = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 0, 0, 0);
		const endOfDay = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 23, 59, 59, 999);

		// 월간 통계용 날짜 범위
		const monthRange = getSearchRange('month');

		// 병렬로 모든 데이터 조회
		const [
			allContents,
			todayCalendars,
			keywords,
			monthlyContents,
		] = await Promise.all([
			// 전체 콘텐츠 (최근 콘텐츠 + 북마크용)
			contentService.getAllContents(pid, email, { contentFilter: Enums.ContentFilter.ALL }),
			// 오늘의 캘린더/회의 일정
			calendarService.getCalendars({ pid }, member, {
				startDate: startOfDay,
				endDate: endOfDay,
			}),
			// 검색 키워드 히스토리
			searchModel.getKeywordsHistory(pid),
			// 월간 콘텐츠 (사용량 통계용)
			this.contentModel.getUserContents(pid, monthRange),
		]);

		// 완료된 콘텐츠만 필터링
		const doneContents = allContents.filter(content => content.transcribeStatus === 'DONE');
		const contentIds = doneContents.map(content => content.contentId);

		// 진행 중인 콘텐츠 (WAITING, PROCESSING 상태)
		const progressContents = allContents
			.filter(content => ['WAITING', 'PROCESSING'].includes(content.transcribeStatus))
			.slice(0, 10)
			.map(content => ({
				contentId: content.contentId,
				title: content.editedTitle || content.title,
				type: content.type,
				transcribeStatus: content.transcribeStatus,
				createAt: content.createAt,
				duration: content.duration,
			}));

		// 북마크 조회 (최대 10개)
		const bookmarks = await bookmarkModel.getBookmarks(contentIds, 10);

		// 북마크에 콘텐츠 제목 추가
		bookmarks.forEach(bookmark => {
			const content = allContents.find(content => content.contentId === bookmark.contentId);
			if (content) {
				bookmark.title = content.editedTitle || content.title;
			}
		});

		// 최근 콘텐츠 - 완료된 것만 (최대 10개)
		const recentContents = doneContents.slice(0, 10);

		// 월간 통계 계산
		const monthlySummary = this.calculateMonthlySummary(monthlyContents);

		// 오늘의 회의 (캘린더 데이터에서 추출)
		const todayMeetings = this.processTodayMeetings(todayCalendars, startOfDay, endOfDay);

		return {
			todayMeetings,
			recentContents,
			progressContents,
			monthlySummary,
			bookmarks,
			keywords,
		};
	}

	/**
	 * 월간 사용량 통계 계산
	 */
	calculateMonthlySummary(contents) {
		const stats = usageUtil.getContentsRegistrationStats(contents);

		// 총 녹음/업로드 시간 (ms 단위를 초 단위로 변환)
		const totalDurationMs = contents.reduce((sum, content) => sum + (content.duration || 0), 0);
		const totalDurationSec = Math.floor(totalDurationMs / 1000);

		// 시간 단위로 변환
		const totalHours = Math.floor(totalDurationSec / 3600);
		const totalMinutes = Math.floor((totalDurationSec % 3600) / 60);

		return {
			totalCount: stats.totalContents,
			recordCount: stats.record,
			uploadCount: stats.upload,
			totalDuration: totalDurationSec,
			totalHours,
			totalMinutes,
			formattedDuration: totalHours > 0 ? `${totalHours}시간 ${totalMinutes}분` : `${totalMinutes}분`,
		};
	}

	/**
	 * 오늘의 회의 데이터 처리
	 */
	processTodayMeetings(calendars, startOfDay, endOfDay) {
		if (!calendars || calendars.length === 0) {
			return [];
		}

		// 캘린더 데이터를 회의 형식으로 변환
		return calendars.map(calendar => ({
			id: calendar.id,
			title: calendar.title,
			meetingStartDate: calendar.meetingStartDate,
			meetingEndDate: calendar.meetingEndDate,
			location: calendar.location,
			description: calendar.description,
			contentId: calendar.content?.contentId || null,
			hasContent: !!calendar.content,
			transcribeStatus: calendar.content?.transcribeStatus || null,
			type: calendar.content?.type || null,
			creatorPID: calendar.content?.creatorPID || null,
		}));
	}
}

// Legacy 함수 호환성 유지 (기존 home.router.js에서 사용)
export const dashboardService = async user => {
	const { pid, email } = user;

	const [contents, keywords] = await Promise.all([
		contentService.getAllContents(pid, email, { contentFilter: Enums.ContentFilter.ALL }),
		searchModel.getKeywordsHistory(pid),
	]);

	const filteredContents = contents.filter(content => content.transcribeStatus === 'DONE');
	const contentIds = filteredContents.map(content => content.contentId);
	const bookmarks = await bookmarkModel.getBookmarks(contentIds, 5);

	bookmarks.forEach(bookmark => {
		const content = contents.find(content => content.contentId === bookmark.contentId);
		bookmark.title = content.title;
	});

	return {
		keywords,
		bookmarks,
		contents: filteredContents.slice(0, 5),
	};
};

export default new DashboardService();
