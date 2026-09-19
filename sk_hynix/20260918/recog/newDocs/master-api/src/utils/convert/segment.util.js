import generate from '../generate.util.js';
import { HttpError } from '../../handlers/error.handler.js';

class SegmentUtil {
	processSegments({ segments, maxDuration = 30000, oldSegmentsMap = new Map() }) {
		const mergedSegments = [];
		let currentGroup = null;

		segments.forEach(({ segmentId, speakerId, text, startTime, endTime, duration }) => {
			if (
				!currentGroup ||
				currentGroup.speakerId !== speakerId ||
				currentGroup.duration + duration > maxDuration ||
				endTime - currentGroup.startTime > maxDuration
			) {
				if (currentGroup) {
					mergedSegments.push(currentGroup);
				}
				segmentId = oldSegmentsMap.get(startTime)?.segmentId || segmentId;
				currentGroup = { segmentId, speakerId, text, startTime, endTime, duration };
			} else {
				currentGroup.text += ` ${text}`;
				currentGroup.duration += duration;
				currentGroup.endTime = endTime;

				if (currentGroup.endTime - currentGroup.startTime > maxDuration) {
					const splitPoint = currentGroup.startTime + maxDuration;
					mergedSegments.push({
						segmentId: currentGroup.segmentId,
						speakerId: currentGroup.speakerId,
						text: currentGroup.text,
						startTime: currentGroup.startTime,
						endTime: splitPoint,
						duration: maxDuration,
					});
					currentGroup = {
						segmentId,
						speakerId,
						text,
						startTime: splitPoint,
						endTime,
						duration: endTime - splitPoint,
					};
				}
			}
		});

		if (currentGroup) {
			mergedSegments.push(currentGroup);
		}

		return mergedSegments;
	}

	replaceSegments(segments, corpus) {
		return segments.map(segment => {
			corpus.forEach(({ source, target }) => {
				segment.text = segment.text.replaceAll(source, target);
			});
			return segment;
		});
	}

	createMergedSegments({ segments }) {
		return this.processSegments({ segments });
	}

	resetMergedSegments({ segments, options }) {
		const { oldSegmentsMap, resetSpeaker = 'N', speakerInfo } = options;
		if (resetSpeaker === 'Y' && oldSegmentsMap.size !== 0) {
			const segmentsSpeakerIdSet = new Set();

			for (const { speakerId } of segments) {
				segmentsSpeakerIdSet.add(speakerId);
			}
			if (speakerInfo.length < segmentsSpeakerIdSet.size) throw new HttpError(1505);
		}

		const mergedSegments = this.processSegments({ segments, oldSegmentsMap });

		if (resetSpeaker === 'N' && oldSegmentsMap.size !== 0) {
			for (const [index, segment] of mergedSegments.entries()) {
				const oldSegmentInfo = oldSegmentsMap.get(segment.startTime);
				if (segment.speakerId !== oldSegmentInfo?.speakerId) {
					mergedSegments[index].speakerId = oldSegmentInfo?.speakerId;
				}
			}
		}

		return mergedSegments;
	}

	convertTextSplitter = (chunks, { language }) => {
		const name = language === 'ko' ? '참석자' : 'participant';
		const duration = 30000;

		const speakerMap = {};
		const segments = [];

		chunks.forEach((chunk, index) => {
			let speakerId = 1;

			if (!speakerMap.hasOwnProperty(speakerId)) {
				speakerMap[speakerId] = {
					speakerId,
					name: `${name} ${speakerId}`,
				};
			}

			const startTime = index * duration;
			const endTime = startTime + duration;

			segments.push({
				speakerId,
				segmentId: generate.uuid(),
				startTime,
				endTime,
				duration,
				text: chunk,
			});
		});

		return {
			'speakerInfo': Object.values(speakerMap),
			'speakerMap': speakerMap,
			'segments': segments,
		};
	};
}

export default new SegmentUtil();
