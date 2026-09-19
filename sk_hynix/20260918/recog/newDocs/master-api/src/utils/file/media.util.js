import fs from 'fs';
import path from 'path';
import util from 'util';
import ffmpeg from 'fluent-ffmpeg';
import { HttpError } from '../../handlers/error.handler.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';

class MediaUtil {
	constructor() {
		log.i('[MediaUtils : constructor] MediaUtils is created');
		this.ffprobe = util.promisify(ffmpeg.ffprobe);
	}

	isRecogTarget({ mimetype }) {
		return (
			mimetype.startsWith('audio/') || mimetype.startsWith('video/') || mimetype.indexOf('octet-stream') !== -1
		);
	}

	async getFileMeta(path) {
		try {
			const ffprobeResult = await this.ffprobe(path);
			const { duration, tags = {} } = ffprobeResult.format;
			const creationTimeKey = ['creation_time', 'create_at'].find(key => tags?.[key]);

			log.i('[MediaUtils : getDuration] duration =>', duration);
			return {
				duration: duration * 1000,
				creationTime: creationTimeKey ? tags[creationTimeKey] : null,
			};
		} catch (err) {
			log.e('[MediaUtils : getDuration] error : ', err.message);
			return 0;
		}
	}

	parseFileType({ inputType = null }, { mimeType }) {
		try {
			let type = mimeType.split('/')[0];
			if (inputType === null) return Enums.ContentType[type.toUpperCase()];

			return Enums.ContentType[inputType.toUpperCase()];
		} catch (err) {
			return undefined;
		}
	}

	getExtension(filename) {
		const lastDotIndex = filename.lastIndexOf('.');
		const extension = lastDotIndex !== -1 ? filename.substring(lastDotIndex + 1) : '';
		return extension;
	}

	async processMediaFile(file, data) {
		const tempFilePath = `./tmp/tmp-${data.apiKey}-${Date.now()}.${this.getExtension(file.originalname)}`;
		fs.writeFileSync(tempFilePath, file.buffer);

		data.inputType = this.parseFileType(file, data);
		const { duration, creationTime } = await this.getFileMeta(tempFilePath);
		data.duration = duration;
		data.creationTime = creationTime;
		if (isNaN(data.duration)) {
			throw new HttpError(1126);
		} else if (!data.inputType) {
			data.inputType = Enums.ContentType.AUDIO;
		}
		return tempFilePath;
	}

	async parseMediaFile(file, fileData) {
		if (this.isRecogTarget(file)) {
			return await this.processMediaFile(file, fileData);
		}
		return null;
	}

	async parsePcmFile(filePath, fileList, num = null, totalNum, originalnames) {
		try {
			for (let i = 0; i < fileList.length; i++) {
				const fragmentFilePath = path.join(
					filePath,
					num ? `${num}_${totalNum}_${originalnames[i]}` : originalnames[i]
				);
				await fs.promises.writeFile(fragmentFilePath, fileList[i].buffer);
			}
		} catch (err) {
			await fs.promises.rm(fragmentFilePath, { force: true }).catch(() => {});
			log.e('[MediaUtil : parsePcmFile] error : ', err.message);
			throw err;
		}
	}
}

export default new MediaUtil();
