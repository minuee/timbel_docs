import { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType } from 'docx';

class DocxMaker {
	constructor(koreanFont) {
		this.koreanFont = koreanFont;
		this.paragraphs = [];
		this.documentOptions = {
			creator: '회의록 시스템',
			description: '회의 내용',
			title: '회의록',
		};
	}

	// 제목 설정
	setTitle(title) {
		this.documentOptions.title = title;
	}

	async createDocx(textObject, title) {
		try {
			// 문서 제목 설정 (필요시)
			if (title) {
				this.setTitle(title);
				// title 값을 문서 내부에도 문자열로 추가 (크기 조절)
				this.paragraphs.push(
					new Paragraph({
						children: [
							new TextRun({
								text: title,
								size: 32, // 기본 크기(24)보다 약간 크게 설정
								bold: true,
							}),
						],
						heading: HeadingLevel.TITLE,
						alignment: AlignmentType.CENTER,
					})
				);
				this.paragraphs.push(new Paragraph({ spacing: { before: 120, after: 120 } }));
			}

			// Docx 객체에 콘텐츠와 스타일 추가
			this.processTextObjects(textObject);

			// buffer 생성 및 반환
			const buffer = await this.generate();
			return buffer;
		} catch (err) {
			console.error('DOCX 생성 오류:', err);
			throw err;
		}
	}

	// 텍스트 객체 배열을 처리하는 메서드
	processTextObjects(textObjects) {
		let currentTextObjects = [];
		let currentIsHeading = false;

		// 각 텍스트 객체를 순회하며 처리
		for (const obj of textObjects) {
			const text = obj.text || '';
			const styles = obj.styles || {};
			const hasNewLine = text.endsWith('\n');

			// 헤딩 여부 확인
			const isHeading =
				styles.heading === true ||
				(styles.size && styles.size >= 16) ||
				(styles.fontSize && styles.fontSize >= 16);

			// 빈 줄바꿈만 있는 경우: 현재 텍스트 객체들로 문단 생성 후 빈 줄 추가
			if (text === '\n') {
				if (currentTextObjects.length > 0) {
					this.createParagraphFromTextObjects(currentTextObjects, currentIsHeading);
					currentTextObjects = [];
					currentIsHeading = false;
				}
				// 빈 줄 추가
				this.paragraphs.push(new Paragraph({ spacing: { before: 120, after: 120 } }));
				continue;
			}

			// 텍스트 앞부분이 헤딩이거나 줄바꿈이 있는 경우: 새 문단 시작
			if (currentTextObjects.length === 0) {
				currentIsHeading = isHeading;
			}

			// 텍스트 객체를 현재 그룹에 추가
			currentTextObjects.push({
				text: hasNewLine ? text.slice(0, -1) : text,
				styles: styles,
			});

			// 줄바꿈이 있는 경우: 현재 텍스트 객체들로 문단 생성 후 초기화
			if (hasNewLine) {
				this.createParagraphFromTextObjects(currentTextObjects, currentIsHeading);
				currentTextObjects = [];
				currentIsHeading = false;
			}
		}

		// 남은 텍스트 객체들이 있으면 문단 생성
		if (currentTextObjects.length > 0) {
			this.createParagraphFromTextObjects(currentTextObjects, currentIsHeading);
		}
	}

	// 텍스트 객체 배열로 문단 생성
	createParagraphFromTextObjects(textObjects, isHeading) {
		const children = textObjects.map(obj => {
			const styles = obj.styles || {};

			const options = {
				text: obj.text,
				bold: styles.bold === true,
				size:
					styles.size ? parseInt(styles.size * 2)
					: styles.fontSize ? parseInt(styles.fontSize * 2)
					: 24,
			};

			// 하이라이트 처리
			if (styles.highlight === true || styles.backgroundColor) {
				options.highlight = this.convertHighlightColor(styles.backgroundColor || '#BBFFAA');
			}

			return new TextRun(options);
		});

		const paragraph = new Paragraph({
			children: children,
			heading: isHeading ? HeadingLevel.TITLE : undefined,
			spacing: isHeading ? { before: 240, after: 120 } : { before: 60, after: 60 },
			alignment: this.convertAlignment(textObjects[0]?.styles?.alignment),
		});

		this.paragraphs.push(paragraph);
	}

	// 문서 생성 및 버퍼 반환
	async generate() {
		const document = new Document({
			...this.documentOptions,
			sections: [
				{
					children: this.paragraphs,
				},
			],
		});

		return Packer.toBuffer(document);
	}

	// 정렬 변환
	convertAlignment(alignment) {
		if (!alignment) return AlignmentType.LEFT;

		const alignmentMap = {
			'left': AlignmentType.LEFT,
			'center': AlignmentType.CENTER,
			'right': AlignmentType.RIGHT,
			'justify': AlignmentType.JUSTIFIED,
		};

		return alignmentMap[alignment] || AlignmentType.LEFT;
	}

	// 하이라이트(배경색) 변환
	convertHighlightColor(color) {
		// 색상 코드에서 하이라이트 색상으로 변환
		const colorMap = {
			'#FFFF99': 'yellow',
			'#FF9999': 'pink',
			'#99FF99': 'green',
			'#9999FF': 'blue',
			'#BBFFAA': 'green',
		};

		return colorMap[color] || 'green'; // 기본값은 노란색
	}
}

export default DocxMaker;
