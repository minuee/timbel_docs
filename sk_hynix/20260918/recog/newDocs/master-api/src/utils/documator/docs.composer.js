import convertUtil from '../convert/index.js';

const printConfig = {
	styles: {
		default: {
			// heading1: { fontSize: 18, bold: true, alignment: 'center' },
			// heading2: { fontSize: 16, bold: true, alignment: 'left' },
			heading2: { size: 16, bold: true },
			// paragraph: { fontSize: 12, alignment: 'left' },
			// highlight: { fontSize: 12, bold: false, backgroundColor: '#FFFF99' },
			highlight: { highlight: true },
		},
	},
	labels: {
		recap: {
			topics: '주제',
			keywords: '키워드',
			speakerInfo: '참석자',
			summary: '핵심 요약',
			tasks: '할 일',
			issues: '이슈',
			summaryTime: '주제별 상세 요약',
		},
		segments: '음성 기록',
		note: '노트',
		bookmarks: '북마크',
		get bookmarkKeys() {
			return {
				...this.recap,
				segments: this.segments,
			};
		},
	},
};

export function composeContent(originalData, includeKeys) {
	// 사용 가능한 키 및 처리할 키 준비
	const availableKeys = ['recap', 'bookmarks', 'segments', 'note', 'highlights'];
	const keysToProcess =
		includeKeys && includeKeys.length > 0 ? includeKeys.filter(key => availableKeys.includes(key)) : availableKeys;

	// 순서 정렬
	keysToProcess.sort((a, b) => availableKeys.indexOf(a) - availableKeys.indexOf(b));

	const { aiResult, speakerInfo = [], summaryTime = [], bookmarks, note, highlights = [], ...rest } = originalData;

	// recap
	const { topics = [], summary = [], keywords = [], tasks = [], issues = [] } = aiResult || {};
	const recap = { topics, speakerInfo, keywords, summary, issues, tasks, summaryTime };

	// segments
	let { mergedSegments } = rest;

	const resolver = {
		tasks: composeTasks,
		issues: composeIssues,
		topics: composeTopics,
		summary: composeSummary,
		keywords: composeKeywords,
		speakerInfo: composeSpeakerInfo,
		summaryTime: composeSummaryTime,
		segments: composeSegments,
		note: composeNote,
		bookmarks: composeBookmarks,
	};

	const content = [];

	// keysToProcess에 포함된 것만 처리
	keysToProcess.forEach(includeKey => {
		if (recap && includeKey === 'recap') {
			Object.keys(recap).forEach(includeKey => {
				// 현재 항목에 맞는 하이라이트만 필터링
				const filteredHighlights = highlights.filter(highlight => {
					return Object.keys(recap).includes(highlight.category.key);
				});

				content.push(...resolver[includeKey](includeKey, recap[includeKey], filteredHighlights));
			});
		}

		if (mergedSegments && includeKey === 'segments') {
			const speakerInfo = recap.speakerInfo;
			const filteredHighlights = highlights.filter(highlight => highlight.category.key === 'mergedSegments');
			content.push(...resolver[includeKey](includeKey, mergedSegments, speakerInfo, filteredHighlights));
		}

		if (note && includeKey === 'note') {
			content.push(...resolver[includeKey](includeKey, note));
		}

		if (bookmarks && includeKey === 'bookmarks') {
			content.push(...resolver[includeKey](includeKey, bookmarks, speakerInfo));
		}
	});

	return content;
}

/**
 * ----------------------------------------------
 * 전체 요약 탭
 * ----------------------------------------------
 */

function composeTopics(key, values, highlights) {
	const content = [composeLabel(key, true)];

	values.forEach((value, valueIndex) => {
		const params = { text: value, highlights, key, valueIndex };
		const processedTexts = processTextWithHighlights(params);
		content.push(...processedTexts);
	});

	content.push({ text: '\n' });

	return content;
}

function composeSpeakerInfo(key, values) {
	const content = [composeLabel(key, true)];

	const text = values.map(value => value.displayName || value.name).join(', ');

	content.push({ text: text + '\n' });
	content.push({ text: '\n' });

	return content;
}

function composeKeywords(key, values) {
	const content = [composeLabel(key, true)];

	content.push({ text: values.join(', ') + '\n' });
	content.push({ text: '\n' });

	return content;
}

function composeSummary(key, values, highlights) {
	const content = [composeLabel(key, true)];

	values.forEach((value, valueIndex) => {
		const params = { text: value, highlights, key, valueIndex };
		const processedTexts = processTextWithHighlights(params);
		content.push(...processedTexts);
	});

	content.push({ text: '\n' });

	return content;
}

function composeIssues(key, values, highlights) {
	const content = [composeLabel(key, true)];

	values.forEach((value, valueIndex) => {
		const params = { text: value, highlights, key, valueIndex };
		const processedTexts = processTextWithHighlights(params);
		content.push(...processedTexts);
	});

	content.push({ text: '\n' });

	return content;
}

function composeTasks(key, values, highlights) {
	const content = [composeLabel(key, true)];

	values.forEach((value, valueIndex) => {
		if (value) {
			const params = { text: value, highlights, key, valueIndex };
			const processedTexts = processTextWithHighlights(params);
			content.push(...processedTexts);
		}
	});

	content.push({ text: '\n' });

	return content;
}

function composeSummaryTime(key, values, highlights) {
	const content = [composeLabel(key, true)];

	values.forEach((value, valueIndex) => {
		const { topic, time, summary, issues, tasks } = value;
		// 1. 토픽 처리
		if (topic) {
			const params = { text: topic, highlights, key, subKey: 'topic', valueIndex };
			const processedTopicTexts = processTextWithHighlights(params);
			content.push(...processedTopicTexts);
		}

		if (time) {
			content.push({ text: `${time}` + '\n' });
		}

		// 2. 요약 내용 처리
		if (summary && summary.length > 0) {
			summary.forEach((item, subIndex) => {
				const params = { text: item.content, highlights, key, subKey: 'summary', valueIndex, subIndex };
				const processedSummaryTexts = processTextWithHighlights(params);
				content.push(...processedSummaryTexts);
			});
		}

		// 3. 이슈 처리
		if (issues && issues.length > 0) {
			issues.forEach((item, subIndex) => {
				const params = { text: item.content, highlights, key, subKey: 'issues', valueIndex, subIndex };
				const processedIssueTexts = processTextWithHighlights(params);
				content.push({ text: '-이슈: ' }, ...processedIssueTexts);
			});
		}

		// 4. 할일 처리
		if (tasks && tasks.length > 0) {
			tasks.forEach((item, subIndex) => {
				const params = {
					text: item.content,
					highlights,
					key,
					subKey: 'tasks',
					valueIndex,
					subIndex,
				};
				const processedTaskTexts = processTextWithHighlights(params);
				content.push({ text: '-할일: ' }, ...processedTaskTexts);
			});
		}
		content.push({ text: '\n' });
	});

	return content;
}

/**
 * ----------------------------------------------
 * 세그먼트, 노트, 북마크
 * ----------------------------------------------
 */

function composeSegments(key, values, speakerInfo, highlights) {
	const content = [composeLabel(key, false)];
	const { timeFormat } = convertUtil;

	const speakerInfoMap = new Map(speakerInfo.map(info => [info.speakerId, info.displayName || info.name]));

	values.forEach((value, valueIndex) => {
		const { speakerId, text, startTime, endTime } = value;

		if (speakerId && startTime && endTime) {
			content.push({
				text: `${speakerInfoMap.get(speakerId)}: ${timeFormat(startTime)} ~ ${timeFormat(endTime)}\n`,
			});
		}

		if (text) {
			const params = { text, highlights, key: 'mergedSegments', subKey: null, valueIndex };

			const processedTexts = processTextWithHighlights(params);
			content.push(...processedTexts);
		}

		content.push({ text: '\n' });
	});
	return content;
}

function composeNote(key, value) {
	const content = [composeLabel(key, false)];

	// HTML 태그를 기준으로 텍스트 분리 및 처리
	const processHtmlContent = htmlContent => {
		// 0. HTML 엔티티 디코딩
		let processedContent = htmlContent
			// &nbsp; 변환
			.replace(/&nbsp;/g, ' ')
			// 기타 HTML 엔티티도 필요에 따라 처리
			.replace(/&lt;/g, '<')
			.replace(/&gt;/g, '>')
			.replace(/&amp;/g, '&')
			.replace(/&quot;/g, '"')
			.replace(/&#39;/g, "'");

		// 추가: 유니코드 제어 문자 정리 (U+2060 등)
		processedContent = processedContent.replace(/[\u2000-\u200F\u2028-\u202F\u205F-\u206F\uFEFF]/g, '');

		// 2. 연속된 줄바꿈을 하나로 통일
		processedContent = processedContent
			// 1. 연속된 <br/> 두 개를 두 번 줄바꿈으로 변환
			.replace(/(<br\/>\s*){2,}/g, '\n\n')
			// 2. 남은 <p>는 한 번 줄바꿈으로 변환
			.replace(/<p>(.*?)<\/p>/gi, '$1\n')
			// 3. 남은 <br/>는 한 번 줄바꿈으로 변환
			.replace(/<br\/>/g, '\n')
			// 4. 나머지 모든 HTML 태그 제거
			.replace(/<[^>]+>/g, '');

		// 3. 줄바꿈으로 분리하여 텍스트 객체 배열 생성
		const segments = processedContent
			.split('\n\n')
			.filter(line => line.trim().length > 0)
			.map(line => ({ text: line + '\n' }));

		// 4. 각 텍스트 객체 사이에 줄바꿈 객체 추가
		const result = [];
		segments.forEach((segment, index) => {
			// 텍스트 내용을 줄바꿈을 기준으로 분리
			const lines = segment.text.split('\n');
			lines.forEach((line, lineIndex) => {
				if (line.trim()) {
					result.push({ text: line + '\n' });
				}
			});

			// 마지막 세그먼트가 아니면 줄바꿈 객체 추가
			if (index < segments.length - 1) {
				result.push({ text: '\n' });
			} else {
				result.push({ text: '\n\n' });
			}
		});

		return result;
	};

	// HTML 컨텐츠 처리 및 결과 추가
	const processedContent = processHtmlContent(value.content);
	content.push(...processedContent);

	return content;
}

function composeBookmarks(key, value, speakerInfo) {
	const content = [composeLabel(key, false)];

	const sortedBookmarks = value.sort((a, b) => new Date(a.time) - new Date(b.time));

	sortedBookmarks.forEach(bookmark => {
		// 북마크 유형에 따라 적절한 함수 직접 호출
		switch (bookmark.key) {
			case 'topics':
				content.push(...composeTopics(bookmark.key, bookmark.data, []));
				break;
			case 'keywords':
				content.push(...composeKeywords(bookmark.key, bookmark.data));
				break;
			case 'speakerInfo':
				content.push(...composeSpeakerInfo(bookmark.key, bookmark.data));
				break;
			case 'tasks':
				content.push(...composeTasks(bookmark.key, bookmark.data, []));
				break;
			case 'issues':
				content.push(...composeIssues(bookmark.key, bookmark.data, []));
				break;
			case 'summary':
				content.push(...composeSummary(bookmark.key, bookmark.data, []));
				break;
			case 'mergedSegments':
				content.push(...composeSegments('segments', bookmark.data, speakerInfo, []));
				break;
			case 'summaryTime':
				content.push(...composeSummaryTime(bookmark.key, bookmark.data, []));
				break;
		}
	});

	return content;
}

/**
 * ----------------------------------------------
 * 레이블 및 하이라이트
 * ----------------------------------------------
 */

function composeLabel(key, isRecap = false) {
	const styles = printConfig.styles.default.heading2;

	if (isRecap) {
		return { text: printConfig.labels.recap[key] + '\n', styles };
	}

	return { text: printConfig.labels[key] + '\n', styles };
}

// 하이라이트를 적용한 텍스트 배열을 반환하는 함수
function processTextWithHighlights(params) {
	let { text, highlights, key, subKey = null, valueIndex, subIndex = 0 } = params;

	// 현재 텍스트에 대한 모든 하이라이트 찾기 (find 대신 filter 사용)
	const relevantHighlights = highlights.filter(h => {
		const baseMatch = h.category.idx === valueIndex;
		if (!baseMatch) return false;

		// sub 키가 없는 경우 (tasks, issues, topics, summary, segments 등)
		if (!subKey) {
			return h.category.key === key && !h.category.sub;
		}

		// 타입 안전한 비교를 위해 숫자로 변환 (한 번만 수행)
		const highlightSubIdx = Number(h.category?.sub?.idx) || 0;

		// sub 키가 있는 경우 (summaryTime)
		return h.category.sub?.key === subKey && highlightSubIdx === subIndex;
	});

	// 하이라이트가 없으면 텍스트를 그대로 반환
	if (relevantHighlights.length === 0) return [{ text: text + '\n' }];

	// 텍스트를 분할할 위치를 기록할 배열 (시작 위치, 끝 위치, 하이라이트 여부)
	const segments = [];

	// 모든 하이라이트 범위에 대해 분할 지점 추가
	relevantHighlights.forEach(highlight => {
		// 안전한 인덱스 처리 및 유효성 검사
		const start = Math.max(0, Math.min(highlight.start, text.length));
		const end = Math.max(start, Math.min(highlight.end, text.length));

		// 하이라이트 시작 지점 추가
		segments.push({ position: start, isStart: true, highlight });
		// 하이라이트 종료 지점 추가
		segments.push({ position: end, isStart: false, highlight });
	});

	// 분할 지점 정렬 (위치 오름차순)
	segments.sort((a, b) => {
		// 위치가 다르면 위치로 정렬
		if (a.position !== b.position) return a.position - b.position;
		// 위치가 같은 경우 종료 지점이 먼저 오도록 (하이라이트 중첩 시 정확하게 처리)
		return a.isStart ? 1 : -1;
	});

	// 하이라이트 상태를 저장할 스택
	const highlightStack = [];
	// 최종 결과 배열
	const result = [];
	// 마지막으로 처리한 위치
	let lastPosition = 0;

	// 모든 분할 지점 처리
	for (let i = 0; i < segments.length; i++) {
		const segment = segments[i];

		// 이전 위치부터 현재 위치까지 텍스트 추출
		if (segment.position > lastPosition) {
			const segmentText = text.substring(lastPosition, segment.position);

			// 현재 하이라이트 상태에 따라 스타일 적용
			if (highlightStack.length > 0) {
				result.push({
					text: segmentText,
					styles: printConfig.styles.default.highlight,
				});
			} else {
				result.push({ text: segmentText });
			}
		}

		// 하이라이트 시작/종료에 따라 스택 업데이트
		if (segment.isStart) {
			highlightStack.push(segment.highlight);
		} else {
			// 스택에서 현재 하이라이트 제거
			const index = highlightStack.findIndex(h => h === segment.highlight);
			if (index !== -1) {
				highlightStack.splice(index, 1);
			}
		}

		// 현재 위치 업데이트
		lastPosition = segment.position;
	}

	// 마지막 부분 처리
	if (lastPosition < text.length) {
		result.push({ text: text.substring(lastPosition) + '\n' });
	} else {
		// 마지막에 줄바꿈 추가
		if (result.length > 0) {
			const lastItem = result[result.length - 1];
			if (!lastItem.text.endsWith('\n')) {
				lastItem.text += '\n';
			}
		}
	}
	return result;
}
