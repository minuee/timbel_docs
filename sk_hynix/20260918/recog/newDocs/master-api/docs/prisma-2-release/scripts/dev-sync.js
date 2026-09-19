#!/usr/bin/env node

import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * 개발용 동기화 스크립트
 * Prisma 빌드 후 빌드된 파일을 node_modules에 동기화
 */

// 현재 작업 디렉토리에서 submodule 경로를 찾습니다
const CURRENT_WORKING_DIR = process.cwd();
const SUBMODULE_PATH = path.join(CURRENT_WORKING_DIR, 'prisma'); // submodule이 'prisma' 폴더에 있다고 가정
const PROJECT_ROOT = fs.existsSync(SUBMODULE_PATH) ? SUBMODULE_PATH : path.join(__dirname, '..');
const DIST_PATH = path.join(PROJECT_ROOT, 'dist');
const NODE_MODULES_TARGET = path.join(CURRENT_WORKING_DIR, 'node_modules/@timbel-timblo-onpremise/prisma/dist');

// 경로 정보 출력
console.log(`📂 현재 작업 디렉토리: ${CURRENT_WORKING_DIR}`);
console.log(`📂 프로젝트 루트: ${PROJECT_ROOT}`);
console.log(`📂 빌드 대상: ${DIST_PATH}`);
console.log(`📂 동기화 대상: ${NODE_MODULES_TARGET}`);

/**
 * TypeScript 선언 파일 이름을 변경합니다
 */
function renameDeclarationFile() {
	const sourceFile = path.join(DIST_PATH, 'base.database.d.ts');
	const targetFile = path.join(DIST_PATH, 'index.d.ts');

	if (fs.existsSync(sourceFile)) {
		fs.renameSync(sourceFile, targetFile);
		console.log('✅ TypeScript 선언 파일 이름 변경 완료: base.database.d.ts → index.d.ts');
	} else if (!fs.existsSync(targetFile)) {
		throw new Error('TypeScript 선언 파일을 찾을 수 없습니다: base.database.d.ts');
	}
}

/**
 * 빌드가 성공했는지 확인합니다
 */
function verifyBuild() {
	const requiredFiles = ['index.esm.js', 'index.cjs', 'index.d.ts'];

	for (const file of requiredFiles) {
		const filePath = path.join(DIST_PATH, file);
		if (!fs.existsSync(filePath)) {
			throw new Error(`빌드 파일이 없습니다: ${file}`);
		}
	}

	console.log('✅ 빌드 파일 검증 완료');
}

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
 * dist 폴더를 node_modules로 동기화합니다
 */
function syncToNodeModules() {
	try {
		console.log('📁 dist 폴더를 node_modules로 동기화 중...');

		// dist 폴더가 존재하는지 확인
		if (!fs.existsSync(DIST_PATH)) {
			throw new Error(`dist 폴더를 찾을 수 없습니다: ${DIST_PATH}`);
		}

		// node_modules 대상 경로가 존재하는지 확인
		if (!fs.existsSync(NODE_MODULES_TARGET)) {
			console.log('⚠️  node_modules 대상 경로가 없습니다. 생성합니다...');
			fs.mkdirSync(NODE_MODULES_TARGET, { recursive: true });
		}

		// dist 폴더의 모든 내용을 node_modules로 복사
		copyDirectory(DIST_PATH, NODE_MODULES_TARGET);

		console.log('✅ node_modules 동기화 완료');
		console.log(`📂 동기화된 경로: ${NODE_MODULES_TARGET}`);

		// 복사된 파일 목록 출력
		const copiedFiles = getAllFiles(NODE_MODULES_TARGET);
		console.log(`📄 동기화된 파일 수: ${copiedFiles.length}개`);
	} catch (error) {
		console.error('❌ node_modules 동기화 중 오류 발생:', error.message);
		throw error;
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

/**
 * 경로 검증 함수
 */
function validatePaths() {
	// 프로젝트 루트에 package.json이 있는지 확인
	const packageJsonPath = path.join(PROJECT_ROOT, 'package.json');
	if (!fs.existsSync(packageJsonPath)) {
		throw new Error(`프로젝트 루트를 찾을 수 없습니다: ${PROJECT_ROOT}`);
	}

	// node_modules 대상 경로의 부모 디렉토리가 존재하는지 확인
	const nodeModulesParent = path.dirname(NODE_MODULES_TARGET);
	if (!fs.existsSync(nodeModulesParent)) {
		throw new Error(`node_modules 디렉토리를 찾을 수 없습니다: ${nodeModulesParent}`);
	}

	console.log('✅ 경로 검증 완료');
}

/**
 * submodule 정리 함수 (불필요한 파일 제거)
 */
function cleanupSubmodule() {
	try {
		console.log('🧹 submodule 정리 중...');

		// dist 폴더 제거
		if (fs.existsSync(DIST_PATH)) {
			fs.rmSync(DIST_PATH, { recursive: true, force: true });
			console.log('✅ dist 폴더 제거 완료');
		}

		// src/libs 폴더 제거 (Prisma 생성 파일들)
		const srcLibsPath = path.join(PROJECT_ROOT, 'src/libs');
		if (fs.existsSync(srcLibsPath)) {
			fs.rmSync(srcLibsPath, { recursive: true, force: true });
			console.log('✅ src/libs 폴더 제거 완료');
		}

		console.log('✅ submodule 정리 완료');
	} catch (error) {
		console.error('⚠️  submodule 정리 중 오류 발생:', error.message);
		// 정리 실패해도 전체 작업은 계속 진행
	}
}

/**
 * 메인 실행 함수
 */
function main() {
	try {
		console.log('🚀 개발용 동기화 시작...');

		// 경로 검증
		validatePaths();

		// 환경 변수 설정
		const env = {
			...process.env,
			PRISMA_MARIA_OUTPUT_PATH: path.join(PROJECT_ROOT, 'src/libs/prismaService/mariaDB'),
			PRISMA_MONGO_OUTPUT_PATH: path.join(PROJECT_ROOT, 'src/libs/prismaService/mongoDB'),
		};

		// 1. Prisma 빌드 (enum 업데이트 포함)
		console.log('🔨 Prisma 빌드 중...');
		execSync('npm run prismaBuild', {
			stdio: 'inherit',
			cwd: PROJECT_ROOT,
			env: env,
		});

		// 2. submodule에서 빌드 수행
		console.log('🔨 submodule에서 빌드 중...');

		// 2-1. submodule 디렉토리로 이동하여 npm install 수행
		console.log('📦 submodule 의존성 설치 중...');
		execSync('npm install', {
			stdio: 'inherit',
			cwd: PROJECT_ROOT,
		});

		// 2-2. submodule에서 빌드 수행
		console.log('🔨 submodule에서 빌드 수행 중...');
		execSync('npm run build', {
			stdio: 'inherit',
			cwd: PROJECT_ROOT,
			env: env,
		});

		// 3. TypeScript 선언 파일 이름 변경
		renameDeclarationFile();

		// 4. 빌드 검증
		verifyBuild();

		// 5. node_modules로 동기화
		syncToNodeModules();

		// 6. submodule 정리 (불필요한 파일 제거)
		cleanupSubmodule();

		console.log('🎉 개발용 동기화 완료!');
		console.log('📦 이제 node_modules/@timbel-timblo-onpremise/prisma에서 테스트할 수 있습니다.');
		process.exit(0);
	} catch (error) {
		console.error('❌ 동기화 실패:', error.message);
		process.exit(1);
	}
}

// 스크립트 실행
main();
