/* eslint-disable no-useless-escape */
import OpenAI from 'openai';
import convert from '../convert/index.js';

const TAG = '[summarizer/openai]';
const totalTokens = {};

let openai = null;
process.on('configChanged', () => {
	openai = new OpenAI({
		apiKey: process.env.LLM_API_KEY,
		organization: process.env.LLM_ORG_ID,
	});
});
const processPrompt = async (segments, prompt, lang = 'ko', ticketId) => {
	try {
		const korLANG = lang === 'ko' ? 'korean' : 'engrish';
		const promptText = prompt.text.replace('#LANG#', korLANG);
		const content = `<body>
        ${JSON.stringify(segments)}
        </body>`;

		const response = await openai.chat.completions.create({
			messages: [
				{ role: 'system', content: promptText },
				{ role: 'user', content },
			],
			model: 'gpt-4o',
			temperature: 0.0,
			top_p: 1,
			max_tokens: 16383,
		});

		const { choices, usage } = response;
		totalTokens[ticketId] += usage.total_tokens;
		log.i(TAG, ` ${prompt.tag} : completed usage ${usage.total_tokens} ticketTotalTokens ${totalTokens[ticketId]}`);

		const { content: resultMessage } = choices[0].message;

		return convert.contentToJsonV2SummaryOnly(resultMessage);
	} catch (err) {
		log.e(`${TAG} error => ${err.message}`);
		return err.message;
	}
};

const reduceResponse = array => {
	return array.reduce((acc, item) => {
		return { ...acc, ...item };
	}, {});
};

const summarizer = async ({ speakerMap, mergedSegments }, prompts, clientLanguage = 'ko', ticketId) => {
	try {
		totalTokens[ticketId] = 0;
		const compressedSegments = mergedSegments.map(({ text, speakerId, startTime }) => {
			return {
				content: text,
				speaker: speakerMap[speakerId].name,
				time: convert.timeFormat(startTime),
			};
		});
		log.i(TAG, `started summarizer with segments len : ${compressedSegments.length} and ${prompts.length} prompts`);
		const responsesArray = await Promise.all(
			prompts.map(prompt => processPrompt(compressedSegments, prompt, clientLanguage, ticketId))
		);

		const totalToken = totalTokens[ticketId];
		log.i(TAG, `completed summarizer with ${responsesArray.length} responses`);
		delete totalTokens[ticketId];

		return { summaryResponses: reduceResponse(responsesArray), totalToken };
	} catch (err) {
		log.e(TAG, `error => ${err.message}`);
		throw err;
	}
};

export default summarizer;
