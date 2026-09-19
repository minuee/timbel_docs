#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * libs 폴더를 dist 폴더로 복사하는 스크립트
 * Prisma 클라이언트 파일들은 난독화하지 않고 그대로 복사
 */

const SOURCE_LIBS_PATH = path.join(__dirname, '../src/libs');
const TARGET_LIBS_PATH = path.join(__dirname, '../dist/libs');

/**
 * 디렉토리를 재귀적으로 복사합니다
 * @param {string} src - 소스 디렉토리 경로
 * @param {string} dest - 대상 디렉토리 경로
 */
function copyDirectory(src, dest) {
	// 대상 디렉토리가 없으면 생성
	if (!fs.existsSync(dest)) {
		fs.mkdirSync(dest, { recursive: true });
	}

	const entries = fs.readdirSync(src, { withFileTypes: true });

	for (const entry of entries) {
		const srcPath = path.join(src, entry.name);
		const destPath = path.join(dest, entry.name);

		if (entry.isDirectory()) {
			copyDirectory(srcPath, destPath);
		} else {
			// 파일 복사
			fs.copyFileSync(srcPath, destPath);
		}
	}
}

/**
 * 메인 실행 함수
 */
function main() {
	try {
		console.log('📁 libs 폴더 복사 시작...');

		// 소스 libs 폴더가 존재하는지 확인
		if (!fs.existsSync(SOURCE_LIBS_PATH)) {
			throw new Error(`소스 libs 폴더를 찾을 수 없습니다: ${SOURCE_LIBS_PATH}`);
		}

		// dist 폴더가 없으면 생성
		const distPath = path.join(__dirname, '../dist');
		if (!fs.existsSync(distPath)) {
			fs.mkdirSync(distPath, { recursive: true });
		}

		// libs 폴더 복사
		copyDirectory(SOURCE_LIBS_PATH, TARGET_LIBS_PATH);

		console.log('✅ libs 폴더 복사 완료');
		console.log(`📂 복사된 경로: ${TARGET_LIBS_PATH}`);

		// 복사된 파일 목록 출력
		const copiedFiles = getAllFiles(TARGET_LIBS_PATH);
		console.log(`📄 복사된 파일 수: ${copiedFiles.length}개`);
	} catch (error) {
		console.error('❌ libs 폴더 복사 중 오류 발생:', error.message);
		process.exit(1);
	}
}

/**
 * 디렉토리 내의 모든 파일을 재귀적으로 가져옵니다
 * @param {string} dir - 디렉토리 경로
 * @returns {string[]} 파일 경로 배열
 */
function getAllFiles(dir) {
	const files = [];
	const entries = fs.readdirSync(dir, { withFileTypes: true });

	for (const entry of entries) {
		const fullPath = path.join(dir, entry.name);
		if (entry.isDirectory()) {
			files.push(...getAllFiles(fullPath));
		} else {
			files.push(fullPath);
		}
	}

	return files;
}

// 스크립트 실행
main();
