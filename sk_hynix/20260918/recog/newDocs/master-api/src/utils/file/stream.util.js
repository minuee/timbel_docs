import fs from 'fs';
import { PassThrough, pipeline } from 'stream';
import historyModel from '../../models/downloadHistory.model.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';

export default class streamUtil {
	constructor({ head, tmpFile, objectParams = null }, req, res) {
		this.head = head;
		this.params = objectParams;
		this.tmpFile = tmpFile;
		this.req = req;
		this.res = res;
		this.closeListener = null;

		return this;
	}

	setMetaData(head) {
		log.i('[streamUtils : setMetaData] 메타데이터 설정 ');
		let { ContentLength, ContentType, originalname } = head;
		if (head && head.metaData) {
			const { metaData } = head;
			originalname = metaData['originalname'];
			ContentLength = metaData['content-length'];
			ContentType = metaData['content-type'];
		} else {
			const { Metadata } = head;
			originalname = Metadata['originalname'];
		}
		return { ContentLength, ContentType, originalname };
	}

	ensureEncoded(originName) {
		try {
			if (originName === decodeURIComponent(originName)) {
				return encodeURIComponent(originName);
			}
		} catch (error) {
			// decodeURIComponent에서 오류가 발생하면 이미 인코딩된 것으로 간주하고 그대로 반환
		}
		return originName;
	}

	setResponseHeaders() {
		let { ContentLength, ContentType, originalname } = this.setMetaData(this.head);
		const {
			headers: { range },
		} = this.req;
		const filename = this.ensureEncoded(originalname);

		this.res.setHeader('Content-Type', ContentType);
		this.res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);

		if (!range) {
			this.res.setHeader('Content-Length', ContentLength);
			return { isStream: false };
		}

		const [rangeStart, rangeEnd] = range.replace(/bytes=/, '').split('-');
		const start = parseInt(rangeStart, 10);
		const end = rangeEnd ? parseInt(rangeEnd, 10) : ContentLength - 1;
		const chunksize = end - start + 1;

		this.res.setHeader('Content-Range', `bytes ${start}-${end}/${ContentLength}`);
		this.res.setHeader('Accept-Ranges', 'bytes');
		this.res.setHeader('Content-Length', chunksize);

		this.res.status(206);

		if (this.params) this.params.Range = `bytes=${start}-${ContentLength - 1}`;

		return { isStream: true, start, end };
	}

	createReadStream(content) {
		const { contentId, title, fileName } = content;
		const { isStream, start, end } = this.option;
		const options = isStream ? { start, end } : {};
		const stream = fs.createReadStream(this.tmpFile.name, options);

		if (isStream) log.i(`[streamUtils : createReadStream] ${start}-${end} ReadStream 생성`);
		else {
			const stats = fs.statSync(this.tmpFile.name);
			const queryDto = {
				contentId,
				type: Enums.DownloadType.MEDIA_FILE,
				size: stats.size,
				workspaceId: this.req.auth.member.workspace.id,
				contentTitle: title,
				fileName,
				userName: this.req.user.nickName,
				email: this.req.user.email,
			};
			historyModel.createDownloadHistory(queryDto);
		}

		return stream;
	}

	createDownloadPipeline(stream, passThrough) {
		return pipeline(stream, passThrough, this.res, err => {
			if (err) {
				log.e('[streamUtils :createDownloadPipeline] Pipeline failed.', err);
			} else {
				log.i('[streamUtils :createDownloadPipeline] File downloaded successfully.');
			}
		});
	}

	handleStreamClose(stream) {
		if (this.closeListener) {
			this.req.removeListener('close', this.closeListener);
		}

		this.closeListener = () => {
			log.i('[streamUtils : handleStreamClose] 파일 스트림 종료');
			stream.destroy();
		};

		this.req.on('close', this.closeListener);
	}

	async response(content) {
		log.i('[streamUtils : response] 스트림 응답 시작');
		this.option = this.setResponseHeaders();
		const readStream = this.createReadStream(content);
		const passThrough = new PassThrough();
		const stream = this.createDownloadPipeline(readStream, passThrough);
		log.i('[streamUtils : response] 스트림 생성 완료');

		this.handleStreamClose(stream);
		log.i('[streamUtils : response] 스트림 응답 완료');
	}
}
