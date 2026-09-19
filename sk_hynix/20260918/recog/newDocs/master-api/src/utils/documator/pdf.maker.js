import fs from 'fs';
import path from 'path';
import PdfMake from 'pdfmake/build/pdfmake.js';
import PdfFonts from 'pdfmake/build/vfs_fonts.js';
import { HttpError } from '../../handlers/error.handler.js';

class PdfMaker {
	constructor(koreanFont) {
		this.koreanFont = koreanFont;
		this.setupFonts();
	}

	// 폰트 설정 메서드
	setupFonts() {
		try {
			// 폰트 파일을 Base64로 인코딩
			const fontData = fs.readFileSync(this.koreanFont.path);
			const fontBase64 = fontData.toString('base64');

			// 파일명 추출
			const fontFileName = path.basename(this.koreanFont.path);
			const fontName = this.koreanFont.fontName || 'NanumGothic';

			// vfs에 폰트 등록
			PdfMake.vfs = PdfFonts.pdfMake ? PdfFonts.pdfMake.vfs : PdfFonts;
			PdfMake.vfs[fontFileName] = fontBase64;

			// 폰트 정의
			PdfMake.fonts = PdfMake.fonts || {};

			// 한글 폰트 추가
			PdfMake.fonts[fontName] = {
				normal: fontFileName,
				bold: fontFileName,
				italics: fontFileName,
				bolditalics: fontFileName,
			};
		} catch (err) {
			throw new HttpError(500, `한글 폰트 로드 실패: ${err.message}`);
		}
	}

	// PDF 문서 생성 메인 메서드
	async createPdf(textObject, title) {
		try {
			// 문서 제목 설정
			const documentTitle = title || '회의록';

			// 문서 콘텐츠 정의
			const documentDefinition = this.createDocumentDefinition(textObject, documentTitle);

			// PDF 생성 및 반환
			return new Promise((resolve, reject) => {
				const pdfDocGenerator = PdfMake.createPdf(documentDefinition);
				pdfDocGenerator.getBuffer(buffer => {
					// PDF 시그니처 확인
					const signature = buffer.subarray(0, 5).toString();
					if (signature !== '%PDF-') {
						console.error('경고: 생성된 버퍼가 유효한 PDF 형식이 아닙니다!');
					}
					resolve(buffer);
				});
			});
		} catch (err) {
			console.error('PDF 생성 오류:', err);
			throw err;
		}
	}

	// 문서 정의 생성 메서드
	createDocumentDefinition(textObject, title) {
		// 한글 폰트 설정
		const fontName = this.koreanFont.fontName || 'NanumGothic';

		// 문서 기본 스타일 정의
		const documentDefinition = {
			info: {
				title: title,
				author: '회의록 시스템',
				subject: '회의 내용',
			},
			defaultStyle: {
				font: fontName,
				fontSize: 12,
				lineHeight: 1.2,
			},
			content: [],
		};

		// 제목 추가
		if (title) {
			documentDefinition.content.push({
				text: title,
				fontSize: 18,
				bold: true,
				alignment: 'center',
				margin: [0, 0, 0, 10],
			});
		}

		// 텍스트 콘텐츠 생성
		const pdfContent = this.processTextObjects(textObject);
		documentDefinition.content.push(...pdfContent);

		return documentDefinition;
	}

	// 텍스트 객체 처리 메서드
	processTextObjects(textObjects) {
		const content = [];
		let currentText = [];

		// 각 텍스트 객체 처리
		for (const obj of Object.values(textObjects)) {
			const text = obj.text || '';
			const styles = obj.styles || {};
			const hasNewLine = text.endsWith('\n');

			// 빈 줄 처리
			if (text === '\n') {
				if (currentText.length > 0) {
					content.push({ text: currentText, margin: [0, 5, 0, 5] });
					currentText = [];
				}
				content.push({ text: '', margin: [0, 10, 0, 10] });
				continue;
			}

			// 현재 텍스트 부분의 스타일 설정
			const textPart = {
				text: hasNewLine ? text.slice(0, -1) : text,
			};

			// 스타일 적용
			if (styles.bold) textPart.bold = true;
			if (styles.size) textPart.fontSize = styles.size;
			if (styles.fontSize) textPart.fontSize = styles.fontSize;
			if (styles.highlight || styles.backgroundColor) {
				textPart.background = styles.backgroundColor || '#BBFFAA';
			}

			// 헤딩 확인
			const isHeading =
				styles.heading === true ||
				(styles.size && styles.size >= 16) ||
				(styles.fontSize && styles.fontSize >= 16);

			// 헤딩이면 새 섹션 시작
			if (isHeading) {
				if (currentText.length > 0) {
					content.push({ text: currentText, margin: [0, 5, 0, 5] });
					currentText = [];
				}

				textPart.bold = true;
				textPart.fontSize = textPart.fontSize || 16;
				textPart.margin = [0, 10, 0, 5];

				content.push(textPart);
				continue;
			}

			// 현재 텍스트 배열에 추가
			currentText.push(textPart);

			// 줄바꿈이 있으면 현재 문단 완성
			if (hasNewLine) {
				const margin = [0, 2, 0, 2];
				content.push({ text: currentText, margin });
				currentText = [];
			}
		}

		// 남은 텍스트가 있으면 추가
		if (currentText.length > 0) {
			content.push({ text: currentText, margin: [0, 2, 0, 2] });
		}

		return content;
	}
}

export default PdfMaker;
