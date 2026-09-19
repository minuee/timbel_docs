import dayjs from 'dayjs';
import ConvertUtil from '../convert/index.js';
import { getDateTime } from '../date.util.js';
import noteModel from '../../models/note.model.js';
import { HttpError } from '../../handlers/error.handler.js';

class NotePasterUtil {
	constructor() {
		this.template = {
			'topics': `<br/>주제
##DATA##<br/>
`,
			'segments': `<br/>전사 기록
##SEGMENTS_CONTENT##
`,
			'segment': `<br/>##SPEAKERNAME## : ##STARTTIME## ~ ##ENDTIME##<br/>
##TEXT##<br/>
`,
			'speakerInfo': `<br/>참석자
##DATA##<br/>
`,
			'keywords': `<br/>키워드
##DATA##<br/>
`,
			'summary': `<br/>핵심 요약
##DATA##<br/>
`,
			'tasks': `<br/>할 일
##DATA##<br/>
`,
			'issues': `<br/>이슈
##DATA##<br/>
`,
			'summaryTime': `<br/>주제별 상세 요약
##SUMMARYTIME_CONTENT##
`,
			'summaryTimeItem': `<br/>##TIME##<br/>
##TOPIC##
##SUMMARY##
##ISSUES##
##TASKS##
<br/>
`,
			'chatbots': `<br/>
##CHATBOT_CONTENT##
`,
			'chatbot': `<br/>##CHATBOTTIME##<br/>
##QUESTION##<br/>
##ANSWER##<br/>
`,
			'bookmarks': `<br/>북마크
##DATA##
`,
			'note': `<br/>노트
##DATA##
`,
			'title': `<br/>회의록 제목
##DATA##
`,
			'default': `<br/>붙여넣은 항목
##DATA##
`,
		};
	}

	async settingItemPastingIntoNote(key, value) {
		try {
			switch (key) {
				case 'segments':
					return await this.setSegments(value);
				case 'topics':
					return this.setTopics(value);
				case 'speakerInfo':
					return this.setSpeakerInfo(value);
				case 'keywords':
					return this.setKeywords(value);
				case 'summary':
					return this.setSummary(value);
				case 'tasks':
					return this.setTasks(value);
				case 'issues':
					return this.setIssues(value);
				case 'summaryTime':
					return this.setSummaryTime(value);
				case 'chatbot':
					return this.setChatbot(value);
				case 'aiResult':
					return await this.setAiResult(value);
				case 'recap':
					return await this.setRecap(value);
				case 'bookmarks':
					return await this.setBookmarks(value);
				case 'note':
					return await this.setNote(value);
				case 'title':
					return await this.setTitle(value);
				default:
					return this.setDefault(value);
			}
		} catch (error) {
			throw error;
		}
	}

	// 세그먼트 처리 통합 함수 (배열 및 단일 처리 모두 포함)
	async setSegments(value) {
		const segments = Array.isArray(value) ? value : [value];
		const { speakerInfo: attendees } = await noteModel.getSpeakerInfo(segments[0].segmentId);

		const segmentsContent = await Promise.all(
			segments.map(segment => this.prepareSegmentContent(segment, attendees))
		);

		return this.template['segments'].replace(
			'##SEGMENTS_CONTENT##',
			Array.isArray(value) ? segmentsContent.join('\n') : segmentsContent[0]
		);
	}

	// 세그먼트 내용 준비 함수 (공통 로직)
	async prepareSegmentContent(segment, attendees) {
		// 시간 형식 변환
		['startTime', 'endTime', 'duration'].forEach(key => {
			if (key in segment) {
				segment[key] = ConvertUtil.convertTimeFormat(segment[key]);
			}
		});

		// 화자 정보 가져오기
		const speaker = attendees.find(attendee => attendee.speakerId === segment.speakerId);
		if (speaker) {
			segment['displayName'] = speaker.displayName || speaker.name;
		} else {
			segment['displayName'] = '참석자';
		}

		// 세그먼트 내용 생성
		return this.template['segment']
			.replace('##SPEAKERNAME##', segment['displayName'])
			.replace('##STARTTIME##', segment['startTime'])
			.replace('##ENDTIME##', segment['endTime'])
			.replace('##TEXT##', segment['text']);
	}

	setTopics(value) {
		return this.template['topics'].replace('##DATA##', value.map(topic => `<br/>${topic}`).join('\n'));
	}

	setSpeakerInfo(value) {
		return this.template['speakerInfo'].replace(
			'##DATA##',
			`<br/>` + value.map(d => `${d['displayName'] || d['name']}`).join(', ')
		);
	}

	setKeywords(value) {
		return this.template['keywords'].replace('##DATA##', `<br/>` + value.join(', '));
	}

	setSummary(value) {
		return this.template['summary'].replace('##DATA##', value.map(element => `<br/>${element}`).join('\n'));
	}

	setTasks(value) {
		return this.template['tasks'].replace('##DATA##', value.map(task => `<br/>${task}`).join('\n'));
	}

	setIssues(value) {
		return this.template['issues'].replace('##DATA##', value.map(issue => `<br/>${issue}`).join('\n'));
	}

	setSummaryTime(value) {
		// 배열인 경우
		if (Array.isArray(value)) {
			const summaryTimeContents = value.map(item => this.formatSummaryTimeItem(item)).join('\n');
			return this.template['summaryTime'].replace('##SUMMARYTIME_CONTENT##', summaryTimeContents.trim());
		}
		// 단일 항목인 경우
		return this.template['summaryTime'].replace('##SUMMARYTIME_CONTENT##', this.formatSummaryTimeItem(value));
	}

	// summaryTime 항목 포맷팅
	formatSummaryTimeItem(value) {
		const summaryContent = value.summary?.map(element => `<br/>${element.content}`).join('\n');
		const issuesContent = value.issues?.map(issue => `<br/>-이슈: ${issue.content}`).join('');
		const tasksContent = value.tasks?.map(task => `<br/>-할일: ${task.content}`).join('');

		const result = this.template['summaryTimeItem']
			.replace('##TIME##', value.time || '')
			.replace('##TOPIC##', value.topic || '')
			.replace('##SUMMARY##', summaryContent || '')
			.replace('##ISSUES##', `${issuesContent ? `${issuesContent}` : ''}`)
			.replace('##TASKS##', `${tasksContent ? `${tasksContent}` : ''}`);

		return result.trim().replace(/(\n\s*){2,}/g, '\n');
	}

	setChatbot(values) {
		const chatbotContents = values.map(value => {
			const { query, content, date, time } = value;

			// content의 \n\n 으로 줄바꿈이므로, 이를 <br/>로 변환
			const answer = content.replace(/\n\n/g, '<br/>');

			const dateTime = getDateTime(date + ' ' + time, 'YYYY-MM-DD HH:mm:ss');
			const localDatetime = dayjs(dateTime).add(9, 'hour').format('YYYY-MM-DD HH:mm:ss');

			const chatbotContent = this.template['chatbot']
				.replace('##CHATBOTTIME##', `챗봇: ${localDatetime}`)
				.replace('##QUESTION##', `Q: ${query}`)
				.replace('##ANSWER##', `A: ${answer}`);
			return chatbotContent;
		});
		return this.template['chatbots'].replace('##CHATBOT_CONTENT##', chatbotContents.join('\n'));
	}

	async setAiResult(value) {
		const aiResultSubkeys = ['topics', 'speakerInfo', 'keywords', 'summary', 'issues', 'tasks'];
		//순서 정렬 aiResultSubkeys 순서대로
		aiResultSubkeys.sort((a, b) => aiResultSubkeys.indexOf(a) - aiResultSubkeys.indexOf(b));

		const results = await Promise.all(
			aiResultSubkeys.map(async itemKey => {
				return `<br/>${await this.settingItemPastingIntoNote(itemKey, value[itemKey])}`;
			})
		);

		return results.join('\n');
	}

	async setRecap(value) {
		const { aiResult, speakerInfo, summaryTime } = value;
		aiResult.speakerInfo = speakerInfo;
		const aiResultText = await this.setAiResult(aiResult);
		const summaryTimeText = await this.setSummaryTime(summaryTime);
		return `${aiResultText}\n${summaryTimeText}`;
	}

	async setBookmarks(value) {
		try {
			// 북마크 시간 순서대로 정렬
			const sortedBookmarks = value.sort((a, b) => new Date(a.time) - new Date(b.time));

			const results = await Promise.all(
				sortedBookmarks.map(async bookmark => {
					const processedContent = await this.settingItemPastingIntoNote(bookmark.key, bookmark.data);
					return processedContent;
				})
			);

			const processedBookmarks = this.template['bookmarks'].replace('##DATA##', results.join('\n'));

			return '------------' + '\n' + processedBookmarks + '------------' + '\n';
		} catch (error) {
			throw new HttpError(400, '북마크 처리에 실패했습니다.');
		}
	}

	async setNote(value) {
		return this.template['note'].replace('##DATA##', value + '\n');
	}

	async setTitle(value) {
		return this.template['title'].replace('##DATA##', value + '\n');
	}

	setDefault(value) {
		try {
			// value에서 객체, 배열, string 타입을 구분하고, 내부의 문자열 요소만 추출하여 반환함
			if (Array.isArray(value)) {
				return value
					.map(element => {
						if (typeof element === 'object') {
							return this.setDefault(element);
						}
						return element.toString();
					})
					.join('\n');
			} else if (typeof value === 'object' && !Array.isArray(value)) {
				return Object.values(value)
					.map(element => {
						if (typeof element === 'object') {
							return this.setDefault(element);
						}

						return element.toString();
					})
					.join('\n');
			} else if (typeof value === 'string') {
				return value;
			}
			throw new HttpError(400, '항목 붙여넣기에 실패했습니다.');
		} catch (error) {
			throw error;
		}
	}
}

export default new NotePasterUtil();

