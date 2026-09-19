/* eslint-disable no-useless-escape */
import axios from 'axios';
import { parse } from '../date.util.js';
import convert from '../convert/index.js';
import { encoding_for_model } from 'tiktoken';
import i18n from '../../configs/i18n-config.js';
import defaultTopicPrompt from '../../prompts/skPrompts/topic.js';
import defaultSummaryPrompt from '../../prompts/skPrompts/summary.js';
import defaultMasteringPrompt from '../../prompts/skPrompts/mastering.js';

const TAG = '[summarizer/sk-custom]';
export const MAX_TOKEN = 2000;
export const MAX_TOKEN_LENGTH = 16000;
const ENC = encoding_for_model('gpt-4o');

export const calcTokenSize = cont => {
	return ENC.encode(cont).length;
};

export const getCompanyHeader = (company, ticketId) => {
	if (!company) return {};
	const { empno, companyCode, deptCode } = company;
	return {
		'aip-company': companyCode,
		'aip-department': deptCode,
		'aip-user': empno,
		'aip-app-id': 'gbaa-agent-mm-summary',
		'aip-transaction-id': ticketId,
	};
};

export const llm = async (tag, promptText, userContent, lang, companyHeader = {}) => {
	const requestData = {
		model: process.env.LLM_MODEL || 'gpt-4o',
		messages: [
			{ role: 'system', content: promptText.replaceAll('##LANG##', lang) },
			{ role: 'user', content: userContent.replaceAll('##LANG##', lang) },
		],
		temperature: 0.0,
		top_p: 1,
		max_tokens: 16383,
	};
	const requestHeaders = {
		Authorization: `Bearer ${process.env.LLM_API_KEY}`,
		'api-key': process.env.LLM_API_KEY,
		'OpenAI-Organization': process.env.LLM_ORG_ID,
		'Content-Type': 'application/json',
		...companyHeader,
	};
	log.i(TAG, `[${tag}] requestHeaders : ${JSON.stringify(requestHeaders)}`);
	log.i(TAG, `[${tag}] requestData : ${JSON.stringify(requestData)}`);
	const { data: response, headers } = await axios.post(process.env.LLM_API_URL, requestData, {
		headers: requestHeaders,
	});
	log.i(TAG, `[${tag}] headers : ${JSON.stringify(headers)}`);

	const { choices, usage } = response;
	log.i(TAG, `[${tag}] completed usage ${usage.total_tokens}`);

	const { content: resultMessage } = choices[0].message;
	log.i(TAG, `[${tag}] resultMessage : ${resultMessage}`);
	return {
		response: convert.contentToJsonV2SummaryOnly(resultMessage),
		token: usage.total_tokens,
	};
};

export const userPromptSplitter = (systemPrompt, transcriptList, n = 0) => {
	const systemTokenLength = calcTokenSize(systemPrompt);
	const transcriptTokenLength = calcTokenSize(JSON.stringify(transcriptList));

	let nSplit = Math.ceil(transcriptTokenLength / (MAX_TOKEN_LENGTH - systemTokenLength - MAX_TOKEN));
	nSplit += n;

	const splitIdxList = [];
	const chunkSize = Math.ceil(transcriptList.length / nSplit);

	for (let i = chunkSize; i < transcriptList.length; i += chunkSize) {
		splitIdxList.push(i);
	}
	if (splitIdxList.length === 0 || splitIdxList[splitIdxList.length - 1] !== transcriptList.length) {
		splitIdxList.push(transcriptList.length);
	}

	const splitResult = [];
	let sIdx = 0;
	for (const eIdx of splitIdxList) {
		splitResult.push(transcriptList.slice(sIdx, eIdx));
		sIdx = eIdx;
	}
	return splitResult;
};

class skCustomProcess {
	constructor({ segmentInfo, summarySize, ticketId, lang, company, user, contentId }) {
		this.lang = lang;
		this.ticketId = ticketId;
		this.summaryRange = this.getSummaryRange(summarySize);
		this.summarySize = summarySize;
		this.companyHeader = getCompanyHeader(company, ticketId);
		this.compressedSegments = this.createCompressedSegments(segmentInfo);
		this.user = user;
		this.contentId = contentId;
		this.prompting = {
			prompt1: defaultTopicPrompt,
			prompt2: defaultSummaryPrompt,
			prompt3: defaultMasteringPrompt,
		};
	}

	contFinderByTime(processedTranscript, startTime, endTime) {
		const ret = [];
		let appendFlg = false;
		for (const sentence of processedTranscript) {
			if (sentence.time === startTime) {
				ret.push(sentence);
				appendFlg = true;
			} else if (sentence.time === endTime) {
				ret.push(sentence);
				break;
			}

			if (appendFlg) ret.push(sentence);
		}
		return ret;
	}

	async topicProcess(transcriptList) {
		try {
			let n = 1;
			let totalToken = 0;
			const transcriptTokenLen = calcTokenSize(JSON.stringify(transcriptList));
			if (transcriptTokenLen > 25000) n = 0;
			else if (transcriptTokenLen < 1000) n = 0;

			const topicsResult = [];
			let { system, instruction, user } = this.prompting['prompt1'];
			instruction = instruction
				.replaceAll('##MIN##', this.summaryRange.min)
				.replaceAll('##MAX##', this.summaryRange.max);
			const chunks = userPromptSplitter(system + instruction, transcriptList, n);

			const llmPromises = chunks.map((chunk, idx) => {
				const inputData = instruction + user.replace('##DATA##', JSON.stringify(chunk));
				return llm(`topic process ${this.ticketId} - ${idx}`, system, inputData, this.lang, this.companyHeader);
			});
			const llmResults = await Promise.all(llmPromises);

			llmResults.forEach(result => {
				topicsResult.push(...result.response['meeting-topics']);
				totalToken += result.token;
			});

			topicsResult.sort((a, b) => parse(a['START_TIME']) - parse(b['START_TIME']));

			const filteredTopicsResult = [];
			let previousTopic = topicsResult[0];
			for (const topic of topicsResult) {
				if (parse(topic['START_TIME']) >= parse(previousTopic['START_TIME'])) {
					const content = this.contFinderByTime(transcriptList, topic['START_TIME'], topic['END_TIME']);
					if (content.length > 0) {
						filteredTopicsResult.push(topic);
					}
				}
				previousTopic = topic;
			}

			return { topicsResult: filteredTopicsResult, totalToken };
		} catch (err) {
			return { topicsResult: [], totalToken: 0 };
		}
	}

	async summaryProcess(topicsResult, transcriptList) {
		try {
			const { system, instruction, user } = this.prompting['prompt2'];
			const summaryResultDict = { topics: [] };
			let totalToken = 0;

			const topicPromises = topicsResult.map(async (topic, idx) => {
				const startTime = topic.START_TIME;
				const endTime = topic.END_TIME;
				const content = this.contFinderByTime(transcriptList, startTime, endTime);
				const summaryResult = { title: '', details: [], issues: [], actionItems: [] };

				const contentChunks = userPromptSplitter(system + instruction, content);
				const chunkPromises = contentChunks.map((chunk, idx2) => {
					const inputData =
						instruction +
						user.replace('##TOPICS##', topic.TOPIC).replace('##DATA##', JSON.stringify(chunk));
					return llm(
						`summary process ${this.ticketId} - ${idx} - ${idx2}`,
						system,
						inputData,
						this.lang,
						this.companyHeader
					);
				});
				const chunkResults = await Promise.all(chunkPromises);

				let topicToken = 0;
				chunkResults.forEach(res => {
					summaryResult.title = res.response.summary.title;
					summaryResult.details.push(...res.response.summary.details);
					if ('issues' in res.response.summary) summaryResult.issues.push(...res.response.summary.issues);

					if ('action-items' in res.response.summary)
						summaryResult.actionItems.push(...res.response.summary['action-items']);

					topicToken += res.token;
				});

				return { summaryResult, topicToken };
			});

			const topicsSummaryResults = await Promise.all(topicPromises);
			topicsSummaryResults.forEach(({ summaryResult, topicToken }) => {
				summaryResultDict.topics.push(summaryResult);
				totalToken += topicToken;
			});

			return { summaryResult: summaryResultDict, totalToken };
		} catch (err) {
			return { summaryResult: { topics: [] }, totalToken: 0 };
		}
	}

	async masteringProcess(summaryResult) {
		try {
			const { system, user } = this.prompting['prompt3'];
			const summaryJson = JSON.stringify(summaryResult);
			const userPrompt = user.replace('##DATA##', summaryJson);

			return await llm(`mastering process ${this.ticketId}`, system, userPrompt, this.lang, this.companyHeader);
		} catch (err) {
			return { response: { title: '', summary: '', keywords: [] }, token: 0 };
		}
	}

	space(tab = 1) {
		const defaultSpace = 3;
		return ' '.repeat(defaultSpace * tab);
	}

	displayFormat(summaryResult, masteringResult, topicsResult) {
		const tasks = [];
		const issues = [];
		const topics = [];
		const topicsData = [];
		const summaryTime = [];
		const visualText = [];

		// 기본 언어를 한국어로 설정하고, 지원되는 언어인 경우 해당 언어 사용
		const t = i18n[this.lang ?? 'ko'];

		visualText.push(`${t.title} :<br/>${masteringResult.title}<br/>`);
		visualText.push(`<br/>${t.keywords} :<br/>${masteringResult.keywords.join(', ')}<br/>`);
		visualText.push(`<br/>${t.summary} :<br/>${masteringResult.summary}<br/>`);
		visualText.push(`<br/>${t.topics} :<br/>`);

		topicsResult.forEach((topic, idx) => {
			topics.push(topic.TOPIC);
			topicsData.push({
				index: idx + 1,
				text: topic.TOPIC,
				start: topic.START_TIME,
				end: topic.END_TIME,
			});
			visualText.push(
				`${this.space()}${idx + 1}.${this.space()}${topic.TOPIC} [${topic.START_TIME} ~ ${topic.END_TIME}]<br/>`
			);
		});

		visualText.push(`<br/><br/>${t.topicsDetailSummary} :<br/>`);
		summaryResult.topics.forEach((topic, idx) => {
			const topicData = topicsData[idx];
			const timeRangeData = `${topicData.start} ~ ${topicData.end}`;
			const object = {
				index: idx + 1,
				topic: topic.title,
				time: timeRangeData,
				summary: [],
				issues: [],
				tasks: [],
			};
			visualText.push(`${this.space()}${idx + 1}. ${topic.title} <br/>`);

			// 세부 사항
			topic.details.forEach(detail => {
				object.summary.push(detail);
				visualText.push(`${this.space(2)}${detail.content}${this.space(1)}<br/>`);
			});

			// 이슈
			if (topic.issues && topic.issues.length > 0) {
				topic.issues.forEach(issue => {
					issues.push(issue.content);
					object.issues.push(issue);
					visualText.push(
						`${this.space(2)}[${t.issue}]${this.space(1)}${issue.content}${this.space(1)}<br/>`
					);
				});
			}

			// 할 일
			if (topic.actionItems && topic.actionItems.length > 0) {
				topic.actionItems.forEach(({ content, assignee, dueDate, timestamp }) => {
					const task = `${content}`;
					tasks.push(task);
					object.tasks.push({
						content: task,
						timestamp,
					});
					visualText.push(
						`${this.space(2)}[${t.task}]${this.space(1)}${content}${this.space(1)}( ${t.assignee}: ${assignee || '-'}${this.space(1)}${t.dueDate}: ${dueDate || '-'} )<br/>`
					);
				});
			}
			visualText.push(`<br/>`);
			summaryTime.push(object);
		});

		return { note: visualText.join(''), issues, tasks, topics, summaryTime };
	}

	getSummaryRange(summarySize) {
		let max = 4; // default 4

		if (summarySize === 'large') max = 8;
		else if (summarySize === 'small') max = 2;
		return { min: 1, max };
	}

	createCompressedSegments(segmentInfo) {
		const { speakerMap, mergedSegments } = segmentInfo;
		return mergedSegments.map(({ text, speakerId, startTime }) => {
			const { name, displayName = null } = speakerMap[speakerId];
			return {
				content: text,
				speaker: displayName ?? name,
				time: convert.timeFormat(startTime),
			};
		});
	}

	async runner() {
		try {
			const { topicsResult, totalToken: topicToken } = await this.topicProcess(this.compressedSegments);

			const { summaryResult, totalToken: summaryToken } = await this.summaryProcess(
				topicsResult,
				this.compressedSegments
			);

			const { response: masteringResult, token: masteringToken } = await this.masteringProcess(summaryResult);

			const { title, summary = '', keywords = [] } = masteringResult;

			const { note, issues, tasks, topics, summaryTime } = this.displayFormat(
				summaryResult,
				masteringResult,
				topicsResult
			);

			const aiResult = {
				tasks: tasks || [],
				issues: issues || [],
				topics: topics || [],
				summary: [summary] || [],
				keywords: keywords || [],
			};

			const totalToken = topicToken + summaryToken + masteringToken;
			log.i(TAG, `[${this.ticketId}] totalToken : ${totalToken}`);
			return { note, title, aiResult, summaryTime, totalToken };
		} catch (err) {
			return { note: err.message, title: '재요약이 필요한 콘텐츠', aiResult: {}, summaryTime: [], totalToken: 0 };
		}
	}
}

export default skCustomProcess;
