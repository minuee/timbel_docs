#!/usr/bin/env node

import fs from 'fs';
import 'dotenv/config';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Prisma 클라이언트에서 Enum들을 자동으로 추출하여 base.database.js에 반영하는 스크립트
 */

const UPDATE_BASE_PATH = process.env.UPDATE_BASE_PATH || '../src/';
console.log(`UPDATE_BASE_PATH: ${UPDATE_BASE_PATH}`);

const BASE_DATABASE_PATH = path.join(__dirname, `${UPDATE_BASE_PATH}base.database.js`);
const MARIA_DB_TYPES_PATH = path.join(__dirname, `${UPDATE_BASE_PATH}libs/prismaService/mariaDB/index.d.ts`);
const MONGO_DB_TYPES_PATH = path.join(__dirname, `${UPDATE_BASE_PATH}libs/prismaService/mongoDB/index.d.ts`);

/**
 * TypeScript 파일에서 Enum export들을 추출
 * @param {string} filePath - TypeScript 파일 경로
 * @returns {Array} 추출된 Enum 목록
 */
function extractEnumsFromTypes(filePath) {
	try {
		const content = fs.readFileSync(filePath, 'utf8');
		const enums = [];

		// export const EnumName: typeof $Enums.EnumName 패턴을 찾음
		const enumPattern = /export const (\w+): typeof \$Enums\.\1/g;
		let match;

		while ((match = enumPattern.exec(content)) !== null) {
			enums.push(match[1]);
		}

		return enums;
	} catch (error) {
		console.error(`Error reading ${filePath}:`, error.message);
		return [];
	}
}

/**
 * base.database.js 파일을 업데이트
 * @param {Array} mariaEnums - MariaDB Enum 목록
 * @param {Array} mongoEnums - MongoDB Enum 목록
 */
function updateBaseDatabase(mariaEnums, mongoEnums) {
	try {
		let content = fs.readFileSync(BASE_DATABASE_PATH, 'utf8');

		// MariaDB import 섹션 생성
		const mariaImports = mariaEnums.map(enumName => `\t${enumName}`).join(',\n');
		const mariaImportSection = `import {
\tPrismaClient as mariaPrisma,
${mariaImports},
} from './libs/prismaService/mariaDB/index.js';`;

		// MongoDB import 섹션 생성 (중복되는 Enum들은 별칭 사용)
		const mongoEnumsWithAliases = mongoEnums
			.filter(enumName => !mariaEnums.includes(enumName))
			.map(enumName => `\t${enumName}`);

		const mongoImports = mongoEnumsWithAliases.join(',\n');
		const mongoImportSection = `import {
\tPrismaClient as mongoPrisma,
${mongoImports},
} from './libs/prismaService/mongoDB/index.js';`;

		console.log(mongoImports);

		// MariaDB Enums 섹션 생성
		const mariaEnumsSection = mariaEnums.map(enumName => `\t${enumName}`).join(',\n');

		const mongoEnumsWithAliasesForExport = mongoEnums
			.filter(enumName => !mariaEnums.includes(enumName))
			.map(enumName => `\t${enumName}`);
		const mongoEnumsSection = mongoEnumsWithAliasesForExport.join(',\n');

		// 기존 import 섹션을 새로운 것으로 교체
		const importRegex =
			/import\s*\{[^}]*\}\s*from\s*['"]\.\/libs\/prismaService\/mariaDB\/index\.js['"];[\s\S]*?import\s*\{[^}]*\}\s*from\s*['"]\.\/libs\/prismaService\/mongoDB\/index\.js['"];/;
		const newImports = `${mariaImportSection}\n${mongoImportSection}`;
		content = content.replace(importRegex, newImports);

		// Enums 객체 업데이트
		const enumsObjectRegex = /const Enums = \{[^}]*\};/s;
		const newEnumsObject = `const Enums = {
\t// MariaDB Enums
${mariaEnumsSection},

\t// MongoDB Enums
${mongoEnumsSection},

\t// Custom Enums
\tContentFilter,
};`;
		content = content.replace(enumsObjectRegex, newEnumsObject);

		// 파일 저장
		fs.writeFileSync(BASE_DATABASE_PATH, content, 'utf8');
		console.log('✅ base.database.js가 성공적으로 업데이트되었습니다.');
	} catch (error) {
		console.error('❌ base.database.js 업데이트 중 오류 발생:', error.message);
		process.exit(1);
	}
}

/**
 * 메인 실행 함수
 */
function main() {
	console.log('🔄 Prisma Enum 추출 및 base.database.js 업데이트 시작...');

	// 파일 존재 확인
	if (!fs.existsSync(MARIA_DB_TYPES_PATH)) {
		console.error(`❌ MariaDB 타입 파일을 찾을 수 없습니다: ${MARIA_DB_TYPES_PATH}`);
		process.exit(1);
	}

	if (!fs.existsSync(MONGO_DB_TYPES_PATH)) {
		console.error(`❌ MongoDB 타입 파일을 찾을 수 없습니다: ${MONGO_DB_TYPES_PATH}`);
		process.exit(1);
	}

	if (!fs.existsSync(BASE_DATABASE_PATH)) {
		console.error(`❌ base.database.js 파일을 찾을 수 없습니다: ${BASE_DATABASE_PATH}`);
		process.exit(1);
	}

	// Enum 추출
	console.log('📋 MariaDB Enum 추출 중...');
	const mariaEnums = extractEnumsFromTypes(MARIA_DB_TYPES_PATH);
	console.log(`✅ MariaDB에서 ${mariaEnums.length}개의 Enum을 찾았습니다:`, mariaEnums);

	console.log('📋 MongoDB Enum 추출 중...');
	const mongoEnums = extractEnumsFromTypes(MONGO_DB_TYPES_PATH);
	console.log(`✅ MongoDB에서 ${mongoEnums.length}개의 Enum을 찾았습니다:`, mongoEnums);

	// base.database.js 업데이트
	console.log('🔄 base.database.js 업데이트 중...');
	updateBaseDatabase(mariaEnums, mongoEnums);

	console.log('🎉 모든 작업이 완료되었습니다!');
}

// 스크립트 실행
main();

export { extractEnumsFromTypes, updateBaseDatabase };
