import ExcelJS from 'exceljs';
import { HttpError } from '../../handlers/error.handler.js';

class ContactBulkUtil {
	/**
	 * ExcelJS 셀에서 텍스트 값 추출 (하이퍼링크 처리 포함)
	 * @param {ExcelJS.Cell} cell - ExcelJS 셀 객체
	 * @returns {string} - 추출된 텍스트 값
	 */
	extractCellText(cell) {
		if (!cell || cell.value == null) return '';
		if (cell.hyperlink && cell.text) return cell.text;
		if (typeof cell.value === 'object' && cell.value.text) return cell.value.text;

		return String(cell.value);
	}

	/**
	 * 주소록 파일을 읽어서 users 배열로 변환 (CSV/XLSX 자동 감지)
	 * @param {Express.Multer.File} file - 업로드된 파일 (CSV 또는 XLSX)
	 * @returns {Promise<Array<{index: number, email: string, label1: string, label2: string, label3: string, label4: string, label5: string, memo: string}>>}
	 */
	async readContactFile(file) {
		try {
			if (!file) throw new HttpError(1000, '파일이 없습니다');

			const fileExtension = file.originalname.substring(file.originalname.lastIndexOf('.')).toLowerCase();

			if (fileExtension === '.csv') {
				return await this.readCSVFile(file);
			} else if (fileExtension === '.xlsx') {
				return await this.readExcelFile(file);
			} else {
				throw new HttpError(1000, '지원하지 않는 파일 형식입니다. (.csv 또는 .xlsx 파일만 가능합니다)');
			}
		} catch (err) {
			if (err instanceof HttpError) throw err;
			throw new HttpError(1000, `파일 읽기 실패: ${err.message}`);
		}
	}

	/**
	 * 엑셀 파일을 읽어서 users 배열로 변환 (XLSX 전용)
	 * @param {Express.Multer.File} file - 업로드된 엑셀 파일
	 * @returns {Promise<Array<{index: number, email: string, label1: string, label2: string, label3: string, label4: string, label5: string, memo: string}>>}
	 */
	async readExcelFile(file) {
		try {
			if (!file) throw new HttpError(1000, '엑셀 파일이 없습니다');

			// 엑셀 파일 읽기
			const workbook = new ExcelJS.Workbook();
			await workbook.xlsx.load(file.buffer);

			// 첫 번째 시트 선택
			const worksheet = workbook.worksheets[0];
			if (!worksheet) throw new HttpError(1000, '엑셀 시트가 비어있습니다');

			// 헤더 행 추출 (첫 번째 행) - 헤더 이름을 키로 하는 맵 생성
			const headerRow = worksheet.getRow(1);
			const headerMap = new Map(); // colNumber -> headerName 매핑

			headerRow.eachCell({ includeEmpty: false }, (cell, colNumber) => {
				const headerName = cell.value ? String(cell.value).trim() : '';
				if (headerName) {
					headerMap.set(colNumber, headerName);
				}
			});

			if (headerMap.size === 0) {
				throw new HttpError(1000, '엑셀 파일에 헤더가 없습니다');
			}

			// 데이터 행 추출 (2번째 행부터) - 실제 데이터가 있는 행까지만 처리
			const jsonData = [];
			const dataRowNumbers = new Set(); // 데이터가 있는 모든 행 번호 저장
			let firstDataRow = 0; // 첫 번째 데이터 행
			let lastDataRow = 0; // 마지막 데이터 행

			// 먼저 데이터가 있는 모든 행을 찾기
			for (let rowNum = 2; rowNum <= worksheet.rowCount; rowNum++) {
				const row = worksheet.getRow(rowNum);
				let hasData = false;

				row.eachCell({ includeEmpty: true }, (cell, colNumber) => {
					const headerName = headerMap.get(colNumber);
					if (headerName && cell.value !== null && cell.value !== undefined) {
						const value = this.extractCellText(cell);
						if (value.trim()) {
							hasData = true;
						}
					}
				});

				if (hasData) {
					dataRowNumbers.add(rowNum);
					if (firstDataRow === 0) firstDataRow = rowNum;
					lastDataRow = rowNum;
				}
			}

			// 데이터가 있는 행이 없으면 에러
			if (dataRowNumbers.size === 0) {
				throw new HttpError(1000, '엑셀 파일에 데이터가 없습니다');
			}

			// 첫 번째 데이터 행부터 마지막 데이터 행까지 처리 (중간 빈 행 포함)
			const endRow = lastDataRow;
			for (let rowNum = 2; rowNum <= endRow; rowNum++) {
				const row = worksheet.getRow(rowNum);
				const rowData = {};

				row.eachCell({ includeEmpty: true }, (cell, colNumber) => {
					const headerName = headerMap.get(colNumber);
					if (headerName) {
						const value = this.extractCellText(cell);
						rowData[headerName] = value.trim();
					}
				});

				// 모든 행 추가 (빈 행도 포함하여 에러 처리)
				jsonData.push({
					rowData,
					excelRowNumber: rowNum, // 실제 엑셀 행 번호 (1번이 헤더이므로 2번부터)
				});
			}

			if (jsonData.length === 0) {
				throw new HttpError(1000, '엑셀 파일에 데이터가 없습니다');
			}

			// users 배열로 변환 (공통 함수 사용)
			const users = jsonData.map(({ rowData, excelRowNumber }) =>
				this.parseRowDataToUser(rowData, excelRowNumber)
			);

			return users;
		} catch (err) {
			if (err instanceof HttpError) throw err;
			throw new HttpError(1000, `엑셀 파일 읽기 실패: ${err.message}`);
		}
	}

	/**
	 * CSV 파일을 읽어서 users 배열로 변환
	 * @param {Express.Multer.File} file - 업로드된 CSV 파일
	 * @returns {Promise<Array<{index: number, email: string, label1: string, label2: string, label3: string, label4: string, label5: string, memo: string}>>}
	 */
	async readCSVFile(file) {
		try {
			if (!file) throw new HttpError(1000, 'CSV 파일이 없습니다');

			// CSV 파일을 텍스트로 읽기
			const csvText = file.buffer.toString('utf-8');
			const lines = csvText.split(/\r?\n/).filter(line => line.trim() !== ''); // 빈 줄 제거

			if (lines.length < 2) throw new HttpError(1000, 'CSV 파일에 헤더와 데이터가 없습니다');

			// 헤더 행 파싱
			const headerLine = lines[0];
			const headers = this.parseCSVLine(headerLine);
			const headerMap = new Map(); // index -> headerName 매핑

			headers.forEach((header, index) => {
				const headerName = header.trim();
				if (headerName) headerMap.set(index, headerName);
			});

			if (headerMap.size === 0) throw new HttpError(1000, 'CSV 파일에 헤더가 없습니다');

			// 데이터 행 파싱 (2번째 행부터)
			const users = [];
			for (let i = 1; i < lines.length; i++) {
				const dataLine = lines[i];
				const values = this.parseCSVLine(dataLine);
				const rowData = {};

				// 헤더와 매핑하여 객체 생성
				headerMap.forEach((headerName, index) => {
					rowData[headerName] = values[index] ? values[index].trim() : '';
				});

				// 실제 데이터가 있는 행인지 확인
				const hasData = Object.values(rowData).some(value => value && value.trim() !== '');

				// 데이터가 있는 행만 처리 (빈 행은 제외)
				if (hasData) {
					users.push(this.parseRowDataToUser(rowData, i + 1)); // CSV 행 번호 (1번이 헤더이므로 2번부터)
				}
			}

			if (users.length === 0) {
				throw new HttpError(1000, 'CSV 파일에 데이터가 없습니다');
			}

			return users;
		} catch (err) {
			if (err instanceof HttpError) throw err;
			throw new HttpError(1000, `CSV 파일 읽기 실패: ${err.message}`);
		}
	}

	/**
	 * CSV 라인을 파싱 (쉼표로 구분, 따옴표 처리)
	 * @param {string} line - CSV 라인
	 * @returns {string[]} - 파싱된 값 배열
	 */
	parseCSVLine(line) {
		const values = [];
		let current = '';
		let inQuotes = false;

		for (let i = 0; i < line.length; i++) {
			const char = line[i];
			const nextChar = line[i + 1];

			if (char === '"') {
				if (inQuotes && nextChar === '"') {
					// 이스케이프된 따옴표
					current += '"';
					i++; // 다음 따옴표 건너뛰기
				} else {
					// 따옴표 시작/끝
					inQuotes = !inQuotes;
				}
			} else if (char === ',' && !inQuotes) {
				// 쉼표로 구분 (따옴표 밖에서만)
				values.push(current);
				current = '';
			} else {
				current += char;
			}
		}

		// 마지막 값 추가
		values.push(current);

		return values;
	}

	/**
	 * 주소록 일괄 등록용 CSV 양식 파일 생성
	 * @returns {Promise<Buffer>} - CSV 파일 버퍼
	 */
	async generateContactTemplateCSV() {
		try {
			// CSV 헤더
			const headers = [
				'이메일(필수)',
				'라벨1(선택)',
				'라벨2(선택)',
				'라벨3(선택)',
				'라벨4(선택)',
				'라벨5(선택)',
				'비고(선택)',
			];

			// 예시 데이터
			const exampleRow = ['example@domain.com', '', '', '', '', '', ''];

			// CSV 내용 생성
			const csvLines = [headers.join(','), exampleRow.join(',')];

			const csvContent = csvLines.join('\n');
			// UTF-8 BOM 추가 (Excel에서 UTF-8로 인식하도록)
			const BOM = '\uFEFF';
			const buffer = Buffer.from(BOM + csvContent, 'utf-8');

			return buffer;
		} catch (err) {
			throw new HttpError(1000, `CSV 양식 생성 실패: ${err.message}`);
		}
	}

	validateBulkContacts({ users = [], pid, userProfiles = [], existingContacts = [], userLabels = [] }) {
		const results = [];
		const globalErrors = [];
		const usersToCreate = [];

		// 맵 생성
		const profileMap = new Map((userProfiles || []).map(profile => [profile.email, profile]));
		const contactMap = new Map(
			(existingContacts || [])
				.filter(contact => contact && contact.email)
				.map(contact => [contact.email, contact])
		);
		const labelMap = {};
		(userLabels || []).forEach(label => {
			labelMap[label.name] = label.id;
		});

		for (const user of users) {
			const rowErrors = [];
			const { index, email, label1, label2, label3, label4, label5, memo } = user;

			const isEmptyRow = !email && !label1 && !label2 && !label3 && !label4 && !label5 && !memo;
			if (isEmptyRow) {
				rowErrors.push({
					field: '행',
					reason: '빈 행은 처리할 수 없습니다',
				});
				globalErrors.push(`${index}번 행: 빈 행은 처리할 수 없습니다. 데이터를 입력해주세요.`);
				results.push({
					index,
					isPassed: false,
					errors: rowErrors,
					contact: { email: '', label1: '', label2: '', label3: '', label4: '', label5: '', memo: '' },
				});
				continue;
			}

			if (!email) {
				rowErrors.push({
					field: '이메일',
					reason: '이메일이 필수입니다',
				});
				globalErrors.push(`${index}번 행 '이메일': 이메일이 필수입니다.`);
			}

			if (email && !this.isValidEmail(email)) {
				rowErrors.push({
					field: '이메일',
					reason: '올바르지 않은 이메일 형식입니다',
				});
				globalErrors.push(`${index}번 행 '이메일(${email})': 올바르지 않은 이메일 형식입니다.`);
			}

			if (email && !profileMap.has(email)) {
				rowErrors.push({
					field: '이메일',
					reason: '워크스페이스에 가입되지 않은 이메일입니다',
				});
				globalErrors.push(
					`${index}번 행 '이메일(${email})': 워크스페이스에 가입되지 않은 이메일입니다. 회원가입 여부 확인 후 다시 등록해주세요.`
				);
			}

			if (email && profileMap.has(email) && profileMap.get(email).pid === pid) {
				rowErrors.push({
					field: '이메일',
					reason: '자기 자신은 주소록에 등록할 수 없습니다',
				});
				globalErrors.push(`${index}번 행 '이메일(${email})': 자기 자신은 주소록에 등록할 수 없습니다.`);
			}

			const existingContact = email && contactMap.get(email);
			if (existingContact) {
				const reason =
					existingContact.isRecycle ? '휴지통으로 이동된 주소록에 중복된 이메일이 있습니다' : (
						'이미 주소록에 등록된 이메일입니다'
					);
				rowErrors.push({ field: '이메일', reason });
				globalErrors.push(`${index}번 행 '이메일(${email})': ${reason}.`);
			}

			const labels = [
				{ index: 1, name: label1 },
				{ index: 2, name: label2 },
				{ index: 3, name: label3 },
				{ index: 4, name: label4 },
				{ index: 5, name: label5 },
			];

			for (const labelInfo of labels) {
				if (labelInfo.name && !labelMap[labelInfo.name]) {
					rowErrors.push({
						field: `라벨${labelInfo.index}`,
						reason: '존재하지 않은 라벨입니다',
					});
					globalErrors.push(
						`${index}번 행 '라벨${labelInfo.index}(${labelInfo.name})': 존재하지 않은 라벨입니다. 사전에 라벨을 등록해주세요.`
					);
				}
			}

			if (rowErrors.length > 0) {
				results.push({
					index,
					isPassed: false,
					errors: rowErrors,
					contact: { email, label1, label2, label3, label4, label5, memo },
				});
			} else {
				usersToCreate.push(user);
			}
		}

		return { results, globalErrors, usersToCreate, labelMap };
	}

	buildBulkContactsResponse({ users = [], usersToCreate = [], results = [], globalErrors = [] }) {
		for (const user of usersToCreate) {
			results.push({
				index: user.index,
				isPassed: true,
				contact: {
					email: user.email,
					label1: user.label1,
					label2: user.label2,
					label3: user.label3,
					label4: user.label4,
					label5: user.label5,
					memo: user.memo,
				},
			});
		}

		results.sort((a, b) => a.index - b.index);

		const summary = {
			totalCount: users.length,
			successCount: usersToCreate.length,
			failedCount: users.length - usersToCreate.length,
		};

		return {
			summary,
			columns: {
				email: '이메일',
				label1: '라벨1',
				label2: '라벨2',
				label3: '라벨3',
				label4: '라벨4',
				label5: '라벨5',
				memo: '비고',
			},
			results,
			errors: globalErrors,
		};
	}

	/**
	 * 행 데이터를 user 객체로 변환 (공통 로직)
	 * @param {Object} rowData - 행 데이터 객체
	 * @param {number} rowNumber - 행 번호
	 * @returns {{index: number, email: string, label1: string, label2: string, label3: string, label4: string, label5: string, memo: string}}
	 */
	parseRowDataToUser(rowData, rowNumber) {
		const email = this.findValueByKey(rowData, ['email', 'Email', 'EMAIL', '이메일']);
		const label1 = this.findValueByKey(rowData, ['label1', '라벨1']);
		const label2 = this.findValueByKey(rowData, ['label2', '라벨2']);
		const label3 = this.findValueByKey(rowData, ['label3', '라벨3']);
		const label4 = this.findValueByKey(rowData, ['label4', '라벨4']);
		const label5 = this.findValueByKey(rowData, ['label5', '라벨5']);
		const memo = this.findValueByKey(rowData, ['memo', 'Memo', '비고', '메모']);

		// 라벨 중복 제거
		const labels = [label1, label2, label3, label4, label5];
		const uniqueLabels = [];
		const seenLabels = new Set();

		for (const label of labels) {
			if (label && !seenLabels.has(label)) {
				uniqueLabels.push(label);
				seenLabels.add(label);
			}
		}

		// 중복 제거된 라벨을 다시 label1~5에 할당
		const [uniqueLabel1 = '', uniqueLabel2 = '', uniqueLabel3 = '', uniqueLabel4 = '', uniqueLabel5 = ''] =
			uniqueLabels;

		return {
			index: rowNumber,
			email,
			label1: uniqueLabel1,
			label2: uniqueLabel2,
			label3: uniqueLabel3,
			label4: uniqueLabel4,
			label5: uniqueLabel5,
			memo,
		};
	}

	/**
	 * 객체의 키 중 특정 문자열을 포함하는 키를 찾아 값을 반환
	 * @param {Object} row - 엑셀 행 데이터 객체
	 * @param {string[]} searchKeys - 찾을 키 이름 배열 (우선순위 순)
	 * @returns {string}
	 */
	findValueByKey(row, searchKeys) {
		// 먼저 정확한 키 이름으로 검색 (대소문자 구분)
		for (const key of searchKeys) {
			if (row[key] !== undefined && row[key] !== null) {
				return this.normalizeValue(row[key]);
			}
		}

		// 정확한 키가 없으면 키 이름에 포함된 문자열로 검색 (대소문자 무시)
		const rowKeys = Object.keys(row);
		for (const searchKey of searchKeys) {
			const lowerSearchKey = searchKey.toLowerCase();
			for (const rowKey of rowKeys) {
				const lowerRowKey = rowKey.toLowerCase();
				// rowKey가 searchKey를 포함하거나, searchKey가 rowKey를 포함하는 경우
				if (lowerRowKey.includes(lowerSearchKey) || lowerSearchKey.includes(lowerRowKey)) {
					const value = row[rowKey];
					if (value !== undefined && value !== null) {
						return this.normalizeValue(value);
					}
				}
			}
		}

		return '';
	}

	/**
	 * 값 정규화 (공백 제거, 빈 문자열 처리)
	 * @param {*} value
	 * @returns {string}
	 */
	normalizeValue(value) {
		if (value === null || value === undefined) return '';
		return String(value).trim();
	}

	/**
	 * 이메일 형식 검증
	 * @param {string} email
	 * @returns {boolean}
	 */
	isValidEmail(email) {
		const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
		return emailRegex.test(email);
	}

	// 주소록 일괄 등록용 엑셀 양식 파일 생성
	async generateContactTemplate() {
		// 워크북 생성
		const workbook = new ExcelJS.Workbook();
		const worksheet = workbook.addWorksheet('주소록 일괄등록');

		// 헤더 데이터
		const headers = [
			'이메일(필수)',
			'라벨1(선택)',
			'라벨2(선택)',
			'라벨3(선택)',
			'라벨4(선택)',
			'라벨5(선택)',
			'비고(선택)',
		];

		// 헤더 행 추가
		const headerRow = worksheet.addRow(headers);

		// 헤더 행 스타일 설정 (노란색 배경, 굵은 글씨, 가운데 정렬)
		headerRow.eachCell((cell, colNumber) => {
			cell.fill = {
				type: 'pattern',
				pattern: 'solid',
				fgColor: { argb: 'FFFFFF00' }, // 노란색 (FFFF00)
			};
			cell.font = {
				bold: true,
				size: 11,
			};
			cell.alignment = {
				horizontal: 'center',
				vertical: 'middle',
			};
			cell.border = {
				top: { style: 'medium' },
				left: { style: 'medium' },
				bottom: { style: 'medium' },
				right: { style: 'medium' },
			};
			// 헤더 행 셀 잠금 (수정 불가)
			cell.protection = { locked: true };
		});

		// 기본적으로 모든 셀을 잠금 해제 상태로 설정 (2행부터 편집 가능하도록)
		// 1행은 이미 잠금 상태이므로 2행부터만 처리
		worksheet.eachRow((row, rowNumber) => {
			if (rowNumber > 1) {
				row.eachCell({ includeEmpty: true }, cell => {
					cell.protection = { locked: false };
				});
			}
		});

		// 예시 데이터 행 추가
		const exampleRow = worksheet.addRow(['example@domain.com', '', '', '', '', '', '']);

		// 예시 행 스타일 설정 (테두리)
		exampleRow.eachCell((cell, colNumber) => {
			cell.alignment = {
				horizontal: 'center',
				vertical: 'middle',
			};
			cell.numFmt = '@';
		});

		// 예시 행 추가 후 다시 잠금 해제 확인 (2행부터 모든 셀 잠금 해제)
		worksheet.eachRow((row, rowNumber) => {
			if (rowNumber > 1) {
				row.eachCell({ includeEmpty: true }, cell => {
					cell.protection = { locked: false };
				});
			}
		});

		// 열 너비 및 텍스트 서식 설정 (자동 하이퍼링크 방지)
		const columnConfigs = [
			{ col: 1, width: 25 }, // 이메일
			{ col: 2, width: 15 }, // 라벨1
			{ col: 3, width: 15 }, // 라벨2
			{ col: 4, width: 15 }, // 라벨3
			{ col: 5, width: 15 }, // 라벨4
			{ col: 6, width: 15 }, // 라벨5
			{ col: 7, width: 30 }, // 비고
		];

		columnConfigs.forEach(({ col, width }) => {
			const column = worksheet.getColumn(col);
			column.width = width;
			column.numFmt = '@'; // 텍스트 서식 (자동 하이퍼링크 방지)
			column.eachCell({ includeEmpty: true }, (cell, rowNumber) => {
				if (rowNumber > 1) {
					cell.numFmt = '@';
					// 2행부터 모든 셀 잠금 해제 (빈 셀 포함)
					cell.protection = { locked: false };
					// 이메일 열(A열)의 경우 값이 객체 형태(하이퍼링크)일 때 텍스트만 추출
					if (col === 1 && cell.value && typeof cell.value === 'object' && cell.value.text) {
						cell.value = cell.value.text;
					}
				}
			});
		});

		// 헤더 행 높이 설정
		headerRow.height = 25;

		// 2행부터 1000행까지 모든 셀을 명시적으로 잠금 해제 (빈 셀 포함)
		for (let rowNum = 2; rowNum <= 1000; rowNum++) {
			for (let colNum = 1; colNum <= 7; colNum++) {
				const cell = worksheet.getCell(rowNum, colNum);
				cell.protection = { locked: false };
			}
		}

		// 이메일 열에 데이터 유효성 검사 추가 (2행부터 1000행까지)
		// 검증 규칙: 빈 셀 허용 또는 (@ 포함, . 포함, 최대 254자, 세미콜론/쉼표/줄바꿈/공백 불가)
		const emailValidationFormula = `OR(A2="", AND(LEN(A2)<=254, ISNUMBER(SEARCH("@", A2)), ISNUMBER(SEARCH(".", A2)), NOT(ISNUMBER(SEARCH(";", A2))), NOT(ISNUMBER(SEARCH(",", A2))), NOT(ISNUMBER(SEARCH(CHAR(10), A2))), NOT(ISNUMBER(SEARCH(" ", A2)))))`;

		worksheet.dataValidations.add('A2:A1000', {
			type: 'custom',
			formulae: [emailValidationFormula],
			showErrorMessage: true,
			errorStyle: 'stop',
			errorTitle: '잘못된 입력',
			error: '올바른 이메일 형식을 입력해주세요.\n- @와 .(점)이 포함되어야 합니다\n- 최대 254자까지 입력 가능합니다\n- 세미콜론(;), 쉼표(,), 줄바꿈, 공백은 사용할 수 없습니다',
			promptTitle: '이메일 입력',
			prompt: '이메일 주소를 입력하세요. (예: user@example.com)',
		});

		// 경고 메시지 추가 (H1-P1 병합)
		const warningCell = worksheet.getCell('H1');
		warningCell.value = '1행의 엑셀 양식 임의 변경 불가! 2행부터 데이터 입력 가능';
		warningCell.font = {
			color: { argb: 'FFFF0000' }, // 빨간색
			bold: true,
			size: 11,
		};
		warningCell.alignment = {
			horizontal: 'center',
			vertical: 'middle',
		};
		worksheet.mergeCells('H1:P1');

		// 워크시트 보호 활성화 (1행 헤더 수정 불가, 2행부터는 편집 가능)
		// 비밀번호 없이 보호 (사용자가 쉽게 해제할 수 있지만, 실수로 수정하는 것을 방지)
		await worksheet.protect('', {
			selectLockedCells: true, // 잠긴 셀(1행) 선택 가능
			selectUnlockedCells: true, // 잠금 해제된 셀(2행부터) 선택 가능
			formatCells: false, // 셀 서식 변경 불가
			formatColumns: true, // 열 너비 변경 가능
			formatRows: false, // 행 서식 변경 불가
			insertColumns: false, // 열 삽입 불가
			insertRows: true, // 행 삽입 가능 (데이터 추가를 위해)
			insertHyperlinks: false, // 하이퍼링크 삽입 불가
			deleteColumns: false, // 열 삭제 불가
			deleteRows: true, // 행 삭제 가능 (데이터 삭제를 위해)
			sort: true, // 정렬 가능
			autoFilter: true, // 자동 필터 가능
			pivotTables: true, // 피벗 테이블 가능
			editObjects: false, // 객체 편집 불가
			editScenarios: false, // 시나리오 편집 불가
		});

		// 버퍼로 변환
		const buffer = await workbook.xlsx.writeBuffer();

		return Buffer.from(buffer);
	}
}

export default new ContactBulkUtil();

