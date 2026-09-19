import skCustomProcess from './skCustomProcess.js';
import SkaxStreamingProcess from './skaxStream.js';
import skaxCustomProcess from './skaxCustomProcess.js';
import skaxTemplate from './skaxTemplate.js';

const TAG = '[summarizer/index]';
let USE_LLM_MODEL = null;

process.on('configChanged', () => {
	USE_LLM_MODEL = process.env.USE_LLM_MODEL || 'sk-custom';
});
// 추후 LLM 모델 증가를 위해 분리
const summarize = async params => {
	// 환경변수에 따라 다른 프로세서 사용
	const { isMerge = false } = params;

	if (USE_LLM_MODEL === 'skax') {
		log.i(TAG, `Using SKAX LLM Process`);
		return await new skaxCustomProcess(params).runner();
	} else if (USE_LLM_MODEL === 'skax-stream') {
		log.i(TAG, `Using SKAX Stream LLM Process`);
		return await new SkaxStreamingProcess(params).runner();
	} else if (USE_LLM_MODEL === 'skax-template' || isMerge) {
		log.i(TAG, `Using SKAX Template LLM Process`);
		return await new skaxTemplate(params).runner();
	} else {
		log.i(TAG, `Using Default LLM Process`);
		return await new skCustomProcess(params).runner();
	}
};

export default summarize;
