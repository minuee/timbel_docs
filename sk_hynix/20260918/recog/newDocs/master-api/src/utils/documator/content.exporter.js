import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import PdfMaker from './pdf.maker.js';
import HwpMaker from './hwp.maker.js';
import DocxMaker from './docx.maker.js';
import { getDateTime } from '../date.util.js';
import { composeContent } from './docs.composer.js';
import { HttpError } from '../../handlers/error.handler.js';

// ES 모듈에서 __dirname 대체하기
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// 가능한 폰트 경로 후보 목록
const FONT_DIRS = [
	join(__dirname, '../../../assets/fonts'), // 로컬 개발 환경
	'/usr/src/assets/fonts', // 도커 환경
	'/usr/src/app/assets/fonts', // 다른 도커 경로
	'/app/assets/fonts', // 또 다른 도커 경로
];

// 문서 구성기 클래스
class DocumentComposer {
	constructor() {
		this.converters = {
			txt: this.convertToTxt,
			pdf: this.convertToPdf,
			docx: this.convertToDocx,
			hwp: this.convertToHwp,
		};
		// 한글 폰트 여부 확인
		this.koreanFont = this.checkKoreanFontFile();
	}

	// 메인 변환 메서드
	async execute(metadata, contentData, includeKeys) {
		try {
			// 포맷별 폰트 체크
			const format = metadata.format;
			await this.checkKoreanFontForFormat(format);

			const textObject = await composeContent(contentData, includeKeys);

			// 문서 헤더 생성
			const { title, header } = this.createDocumentHeader(metadata);

			// 선택된 전략으로 변환 실행
			const buffer = await this.converters[format].call(this, textObject, title);
			if (!buffer) throw new HttpError(400, `문서 변환 중 오류가 발생했습니다.`);

			// 응답 파일별 헤더 생성
			const fileResponseHeaders = await this.getFileResponseHeaders(title, format);

			return { buffer, ...fileResponseHeaders };
		} catch (err) {
			throw err;
		}
	}

	// 문서 헤더 생성 (공통)
	createDocumentHeader(metadata) {
		const { title, editedTitle, meetingStartTime, meetingEndTime } = metadata;
		const documentTitle = editedTitle || title || `회의록_${getDateTime(new Date(), 'YYYY-MM-DD HH-mm')}`;
		return {
			title: documentTitle,
			header: `회의록 제목: ${documentTitle}\n회의시간: ${getDateTime(meetingStartTime)} ~ ${getDateTime(meetingEndTime)}`,
		};
	}

	// 포맷별 한글 폰트 체크(공통)
	checkKoreanFontForFormat(format) {
		try {
			const needsFont = ['pdf', 'docx', 'hwp'].includes(format);
			if (!needsFont) return true;

			if (!this.koreanFont.isAvailable) {
				throw new HttpError(400, `한글 폰트 사용 불가, ${format} 문서 변환에 실패`);
			}

			return true;
		} catch (err) {
			throw err;
		}
	}

	// 파일 응답을 위한 헤더 생성 (공통)
	getFileResponseHeaders(title, format) {
		const date = getDateTime(new Date(), 'YYMMDD HHmm');

		const defaultFileName = `meeting_content_${date}.${format}`;

		const safeTitle = title.replace(/[\\/:*?"<>|]/g, '_');
		const originalFileName = `${safeTitle}_${date}.${format}`;
		const encodedFileName = encodeURIComponent(originalFileName);

		const contentTypeMap = {
			txt: 'text/plain',
			pdf: 'application/pdf',
			docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
			hwp: 'application/octet-stream',
		};

		return { defaultFileName, encodedFileName, contentType: contentTypeMap[format] };
	}

	/**
	 * ---------------------------------
	 * 이하 포맷별 변환 전략
	 * ---------------------------------
	 */

	convertToTxt(textObject, title) {
		const text = Object.values(textObject)
			.map(item => item.text)
			.join('');
		return text;
	}

	// DOCX 변환 전략
	async convertToDocx(textObject, title) {
		try {
			const docxMaker = new DocxMaker(this.koreanFont);
			return await docxMaker.createDocx(textObject, title);
		} catch (err) {
			console.error('DOCX 생성 오류:', err);
			throw err;
		}
	}

	// PDF 변환 전략
	async convertToPdf(textObject, title) {
		try {
			const pdfMaker = new PdfMaker(this.koreanFont);
			return await pdfMaker.createPdf(textObject, title);
		} catch (err) {
			console.error('PDF 생성 오류:', err);
			throw err;
		}
	}

	// HWP 변환 전략
	async convertToHwp(textObject, title) {
		try {
			const hwpMaker = new HwpMaker(this.koreanFont);
			return await hwpMaker.createHwp(textObject, title);
		} catch (err) {
			console.error('HWP 생성 오류:', err);
			throw err;
		}
	}

	/**
	 * 한글 폰트 파일 존재 유무 체크
	 * @returns {object} 폰트 체크 결과 (isAvailable: 사용 가능 여부, path: 폰트 경로, fonts: 발견된 폰트 목록)
	 */
	checkKoreanFontFile() {
		const discoveredFonts = [];

		// 각 폰트 디렉토리 확인
		for (const fontDir of FONT_DIRS) {
			console.log(`폰트 디렉토리 확인 중: ${fontDir}`);

			// 디렉토리가 존재하는지 확인
			if (!fs.existsSync(fontDir)) {
				console.log(`[warn]디렉토리가 존재하지 않음: ${fontDir}`);
				continue;
			}

			try {
				// 디렉토리 내 모든 파일 목록 가져오기
				const files = fs.readdirSync(fontDir);

				// .ttf 확장자를 가진 파일만 필터링
				const ttfFiles = files.filter(file => file.toLowerCase().endsWith('.ttf'));

				// 발견된 ttf 파일 처리
				for (const ttfFile of ttfFiles) {
					const fontPath = join(fontDir, ttfFile);
					const fontName = ttfFile.split('.')[0];

					discoveredFonts.push({
						path: fontPath,
						name: fontName,
					});
				}

				// 폰트를 찾았으면 첫 번째 폰트 반환
				if (discoveredFonts.length > 0) {
					const primaryFont = discoveredFonts[0];

					return {
						isAvailable: true,
						path: primaryFont.path,
						fontName: primaryFont.name,
						fonts: discoveredFonts, // 모든 발견된 폰트 목록 포함
					};
				}
			} catch (err) {
				console.error(`폰트 디렉토리 읽기 오류 (${fontDir}):`, err);
			}
		}

		// 폰트를 찾지 못한 경우
		console.error('[error]한글 폰트 파일을 찾을 수 없습니다. 기본 폰트를 사용합니다.');
		return { isAvailable: false, path: null, fonts: [] };
	}
}

export default new DocumentComposer();
