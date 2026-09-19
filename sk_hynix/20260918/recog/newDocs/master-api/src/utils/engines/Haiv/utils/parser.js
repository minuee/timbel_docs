// 초 -> 밀리초 변환
const ms = sec => {
	return sec * 1000;
};

// # README의 Segments, speakerInfo, speakerMap 객체 예시와 동일한 응답값 리턴
export const convertUtteStructAndSpeakerInfo = (transcriptions, { language }) => {
	const name = language === 'ko' ? '참석자' : 'participant';

	const speakerMap = {};
	const segments = [];

	transcriptions.forEach(transcription => {
		let speakerId = Number(transcription.speaker);
		if (speakerId === 0) speakerId = 1;
		// speaker
		if (!speakerMap.hasOwnProperty(speakerId)) {
			speakerMap[speakerId] = {
				speakerId,
				name: `${name} ${speakerId}`,
			};
		}

		// segment
		segments.push({
			speakerId,
			segmentId: transcription.id,
			startTime: ms(transcription.start),
			endTime: ms(transcription.start) + ms(transcription.length),
			duration: ms(transcription.length),
			text: transcription.transcript,
		});
	});

	return {
		'speakerInfo': Object.values(speakerMap),
		'speakerMap': speakerMap,
		'segments': segments,
	};
};

export default {
	convertUtteStructAndSpeakerInfo,
};
