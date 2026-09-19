import ExcelJS from 'exceljs';
import { HttpError } from '../../handlers/error.handler.js';

// 키워드 부스팅: 사용자당 최대 개수(FO 생성 로직과 동일)
const KEYWORD_BOOSTING_MAX_COUNT = Number(process.env.KEYWORD_BOOSTING_MAX_COUNT) || 100;
// 키워드 제약: 한글 단어만(FO 생성 로직과 동일), 최대 길이(스키마 VarChar(128))
const KOREAN_ONLY_REGEX = /^[가-힣]+$/;
const KEYWORD_MAX_LENGTH = 128;
// 파일에서 키워드 컬럼을 찾을 때 허용하는 헤더 별칭
const KEYWORD_HEADER_ALIASES = ['키워드', 'keyword', 'Keyword', 'KEYWORD'];

class KeywordBulkUtil {
	extractCellText(cell) {
		if (!cell || cell.value == null) return '';
		if (cell.hyperlink && cell.text) return cell.text;
		if (typeof cell.value === 'object' && cell.value.text) return cell.value.text;
		return String(cell.value);
	}

	normalizeValue(value) {
		if (value === null || value === undefined) return '';
		return String(value).trim();
	}

	findValueByKey(row, searchKeys) {
		for (const key of searchKeys) {
			if (row[key] !== undefined && row[key] !== null) return this.normalizeValue(row[key]);
		}
		const rowKeys = Object.keys(row);
		for (const searchKey of searchKeys) {
			const lowerSearchKey = searchKey.toLowerCase();
			for (const rowKey of rowKeys) {
				const lowerRowKey = rowKey.toLowerCase();
				if (lowerRowKey.includes(lowerSearchKey) || lowerSearchKey.includes(lowerRowKey)) {
					const value = row[rowKey];
					if (value !== undefined && value !== null) return this.normalizeValue(value);
				}
			}
		}
		return '';
	}

	parseRowDataToKeyword(rowData, rowNumber) {
		return {
			index: rowNumber,
			keyword: this.findValueByKey(rowData, KEYWORD_HEADER_ALIASES),
		};
	}

	/**
	 * 업로드 파일을 읽어 [{index, keyword}] 배열로 변환 (CSV/XLSX 자동 감지)
	 */
	async readKeywordFile(file) {
		try {
			if (!file) throw new HttpError(1000, '파일이 없습니다');
			const ext = file.originalname.substring(file.originalname.lastIndexOf('.')).toLowerCase();
			if (ext === '.csv') return await this.readCSVFile(file);
			if (ext === '.xlsx') return await this.readExcelFile(file);
			throw new HttpError(1000, '지원하지 않는 파일 형식입니다. (.csv 또는 .xlsx 파일만 가능합니다)');
		} catch (err) {
			if (err instanceof HttpError) throw err;
			throw new HttpError(1000, `파일 읽기 실패: ${err.message}`);
		}
	}

	async readExcelFile(file) {
		try {
			const workbook = new ExcelJS.Workbook();
			await workbook.xlsx.load(file.buffer);
			const worksheet = workbook.worksheets[0];
			if (!worksheet) throw new HttpError(1000, '엑셀 시트가 비어있습니다');

			const headerRow = worksheet.getRow(1);
			const headerMap = new Map();
			headerRow.eachCell({ includeEmpty: false }, (cell, colNumber) => {
				const headerName = cell.value ? String(cell.value).trim() : '';
				if (headerName) headerMap.set(colNumber, headerName);
			});
			if (headerMap.size === 0) throw new HttpError(1000, '엑셀 파일에 헤더가 없습니다');

			let lastDataRow = 0;
			for (let rowNum = 2; rowNum <= worksheet.rowCount; rowNum++) {
				const row = worksheet.getRow(rowNum);
				let hasData = false;
				row.eachCell({ includeEmpty: true }, (cell, colNumber) => {
					if (headerMap.get(colNumber) && this.extractCellText(cell).trim()) hasData = true;
				});
				if (hasData) lastDataRow = rowNum;
			}
			if (lastDataRow === 0) throw new HttpError(1000, '엑셀 파일에 데이터가 없습니다');

			const keywords = [];
			for (let rowNum = 2; rowNum <= lastDataRow; rowNum++) {
				const row = worksheet.getRow(rowNum);
				const rowData = {};
				row.eachCell({ includeEmpty: true }, (cell, colNumber) => {
					const headerName = headerMap.get(colNumber);
					if (headerName) rowData[headerName] = this.extractCellText(cell).trim();
				});
				keywords.push(this.parseRowDataToKeyword(rowData, rowNum));
			}
			return keywords;
		} catch (err) {
			if (err instanceof HttpError) throw err;
			throw new HttpError(1000, `엑셀 파일 읽기 실패: ${err.message}`);
		}
	}

	async readCSVFile(file) {
		try {
			const csvText = file.buffer.toString('utf-8').replace(/^﻿/, '');
			const lines = csvText.split(/\r?\n/).filter(line => line.trim() !== '');
			if (lines.length < 2) throw new HttpError(1000, 'CSV 파일에 헤더와 데이터가 없습니다');

			const headers = this.parseCSVLine(lines[0]);
			const headerMap = new Map();
			headers.forEach((header, index) => {
				const headerName = header.trim();
				if (headerName) headerMap.set(index, headerName);
			});
			if (headerMap.size === 0) throw new HttpError(1000, 'CSV 파일에 헤더가 없습니다');

			const keywords = [];
			for (let i = 1; i < lines.length; i++) {
				const values = this.parseCSVLine(lines[i]);
				const rowData = {};
				headerMap.forEach((headerName, index) => {
					rowData[headerName] = values[index] ? values[index].trim() : '';
				});
				const hasData = Object.values(rowData).some(v => v && v.trim() !== '');
				if (hasData) keywords.push(this.parseRowDataToKeyword(rowData, i + 1));
			}
			if (keywords.length === 0) throw new HttpError(1000, 'CSV 파일에 데이터가 없습니다');
			return keywords;
		} catch (err) {
			if (err instanceof HttpError) throw err;
			throw new HttpError(1000, `CSV 파일 읽기 실패: ${err.message}`);
		}
	}

	parseCSVLine(line) {
		const values = [];
		let current = '';
		let inQuotes = false;
		for (let i = 0; i < line.length; i++) {
			const char = line[i];
			const nextChar = line[i + 1];
			if (char === '"') {
				if (inQuotes && nextChar === '"') {
					current += '"';
					i++;
				} else {
					inQuotes = !inQuotes;
				}
			} else if (char === ',' && !inQuotes) {
				values.push(current);
				current = '';
			} else {
				current += char;
			}
		}
		values.push(current);
		return values;
	}

	/**
	 * 파일에서 파싱한 키워드 검증.
	 * - 빈 행 / 한글 외 문자 / 128자 초과 / 파일 내 중복 / 기존 보유분 중복 / 100개 상한 초과 → 스킵(사유 리포트)
	 * @returns {{ results, globalErrors, keywordsToCreate }}
	 */
	validateBulkKeywords({ keywords = [], existingKeywords = [], existingCount = 0 }) {
		const results = [];
		const globalErrors = [];
		const keywordsToCreate = [];

		const existingSet = new Set((existingKeywords || []).map(k => (typeof k === 'string' ? k : k.keyword)));
		const seen = new Set();
		let available = Math.max(0, KEYWORD_BOOSTING_MAX_COUNT - existingCount);

		for (const { index, keyword } of keywords) {
			const rowErrors = [];

			if (!keyword) {
				rowErrors.push({ field: '키워드', reason: '빈 행은 처리할 수 없습니다' });
				globalErrors.push(`${index}번 행: 빈 행은 처리할 수 없습니다.`);
				results.push({ index, isPassed: false, errors: rowErrors, keyword: '' });
				continue;
			}

			if (keyword.length > KEYWORD_MAX_LENGTH) {
				rowErrors.push({ field: '키워드', reason: `${KEYWORD_MAX_LENGTH}자를 초과했습니다` });
				globalErrors.push(`${index}번 행 '키워드(${keyword})': ${KEYWORD_MAX_LENGTH}자를 초과했습니다.`);
			}

			if (!KOREAN_ONLY_REGEX.test(keyword)) {
				rowErrors.push({ field: '키워드', reason: '한글 단어만 등록할 수 있습니다' });
				globalErrors.push(`${index}번 행 '키워드(${keyword})': 한글 단어만 등록할 수 있습니다.`);
			} else if (seen.has(keyword)) {
				rowErrors.push({ field: '키워드', reason: '파일 내 중복된 키워드입니다' });
				globalErrors.push(`${index}번 행 '키워드(${keyword})': 파일 내 중복된 키워드입니다.`);
			} else if (existingSet.has(keyword)) {
				rowErrors.push({ field: '키워드', reason: '이미 등록된 키워드입니다' });
				globalErrors.push(`${index}번 행 '키워드(${keyword})': 이미 등록된 키워드입니다.`);
			}

			if (rowErrors.length > 0) {
				results.push({ index, isPassed: false, errors: rowErrors, keyword });
				continue;
			}

			if (available <= 0) {
				rowErrors.push({ field: '키워드', reason: `최대 ${KEYWORD_BOOSTING_MAX_COUNT}개까지만 등록할 수 있습니다` });
				globalErrors.push(
					`${index}번 행 '키워드(${keyword})': 최대 ${KEYWORD_BOOSTING_MAX_COUNT}개까지만 등록할 수 있습니다.`
				);
				results.push({ index, isPassed: false, errors: rowErrors, keyword });
				continue;
			}

			seen.add(keyword);
			available -= 1;
			keywordsToCreate.push(keyword);
		}

		return { results, globalErrors, keywordsToCreate };
	}

	buildBulkKeywordsResponse({ keywords = [], keywordsToCreate = [], results = [], globalErrors = [] }) {
		const createdSet = new Set(keywordsToCreate);
		for (const { index, keyword } of keywords) {
			if (createdSet.has(keyword) && !results.some(r => r.index === index)) {
				results.push({ index, isPassed: true, keyword });
			}
		}
		results.sort((a, b) => a.index - b.index);

		return {
			summary: {
				totalCount: keywords.length,
				successCount: keywordsToCreate.length,
				failedCount: keywords.length - keywordsToCreate.length,
			},
			columns: { keyword: '키워드' },
			results,
			errors: globalErrors,
		};
	}

	/** 키워드 부스팅 일괄 등록용 XLSX 양식(키워드 단일 열) 생성 */
	async generateKeywordTemplate() {
		const workbook = new ExcelJS.Workbook();
		const worksheet = workbook.addWorksheet('키워드 부스팅 일괄등록');

		const headerRow = worksheet.addRow(['키워드(필수)']);
		headerRow.eachCell(cell => {
			cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFF00' } };
			cell.font = { bold: true, size: 11 };
			cell.alignment = { horizontal: 'center', vertical: 'middle' };
			cell.border = {
				top: { style: 'medium' },
				left: { style: 'medium' },
				bottom: { style: 'medium' },
				right: { style: 'medium' },
			};
		});
		headerRow.height = 25;

		worksheet.addRow(['백그라운드']);
		worksheet.addRow(['키워드']);

		const col = worksheet.getColumn(1);
		col.width = 30;
		col.numFmt = '@';
		worksheet.eachRow((row, rowNumber) => {
			if (rowNumber > 1) {
				row.eachCell({ includeEmpty: true }, cell => {
					cell.numFmt = '@';
					cell.alignment = { horizontal: 'center', vertical: 'middle' };
				});
			}
		});

		const warningCell = worksheet.getCell('C1');
		warningCell.value = '1행(헤더)은 수정하지 마세요. 2행부터 한글 키워드를 한 셀에 하나씩 입력하세요.';
		warningCell.font = { color: { argb: 'FFFF0000' }, bold: true, size: 11 };
		warningCell.alignment = { horizontal: 'center', vertical: 'middle' };
		worksheet.mergeCells('C1:K1');

		const buffer = await workbook.xlsx.writeBuffer();
		return Buffer.from(buffer);
	}

	/** 키워드 부스팅 일괄 등록용 CSV 양식(UTF-8 BOM) 생성 */
	async generateKeywordTemplateCSV() {
		const csvContent = ['키워드(필수)', '백그라운드', '키워드'].join('\n');
		return Buffer.from('﻿' + csvContent, 'utf-8');
	}
}

export default new KeywordBulkUtil();
