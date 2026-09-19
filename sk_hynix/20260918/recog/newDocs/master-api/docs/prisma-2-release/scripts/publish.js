#!/usr/bin/env node

import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * GitHub 패키지 배포 스크립트
 */

const PACKAGE_JSON_PATH = path.join(__dirname, '../package.json');
const GITHUB_REGISTRY = 'https://npm.pkg.github.com/';

/**
 * package.json에서 현재 버전을 가져옵니다
 */
function getCurrentVersion() {
	const packageJson = JSON.parse(fs.readFileSync(PACKAGE_JSON_PATH, 'utf8'));
	return packageJson.version;
}

/**
 * npm version 명령어를 사용하여 버전을 증가시킵니다
 */
function incrementVersion() {
	try {
		console.log('📈 버전 증가 중...');
		execSync('npm version patch --no-git-tag-version', {
			stdio: 'inherit',
			cwd: path.join(__dirname, '..'),
		});
		const packageJson = JSON.parse(fs.readFileSync(PACKAGE_JSON_PATH, 'utf8'));
		return packageJson.version;
	} catch (error) {
		console.error('❌ 버전 증가 실패:', error.message);
		throw error;
	}
}

/**
 * Git 상태를 확인합니다
 */
function checkGitStatus() {
	try {
		const status = execSync('git status --porcelain', { encoding: 'utf8' });
		if (status.trim()) {
			console.log('⚠️  Git에 커밋되지 않은 변경사항이 있습니다:');
			console.log(status);
			console.log('계속하려면 Enter를 누르세요...');
			process.stdin.read();
		}
	} catch (error) {
		console.log('⚠️  Git 상태를 확인할 수 없습니다. 계속 진행합니다.');
	}
}

/**
 * TypeScript 선언 파일 이름을 변경합니다
 */
function renameDeclarationFile() {
	const distPath = path.join(__dirname, '../dist');
	const sourceFile = path.join(distPath, 'base.database.d.ts');
	const targetFile = path.join(distPath, 'index.d.ts');

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
	const distPath = path.join(__dirname, '../dist');
	const requiredFiles = ['index.esm.js', 'index.cjs', 'index.d.ts'];

	for (const file of requiredFiles) {
		const filePath = path.join(distPath, file);
		if (!fs.existsSync(filePath)) {
			throw new Error(`빌드 파일이 없습니다: ${file}`);
		}
	}

	console.log('✅ 빌드 파일 검증 완료');
}

/**
 * npm publish를 실행합니다
 */
function publishPackage() {
	try {
		console.log('📦 GitHub 패키지 레지스트리에 배포 중...');
		execSync('npm publish', {
			stdio: 'inherit',
			env: { ...process.env, NODE_ENV: 'production' },
		});
		console.log('✅ 배포가 완료되었습니다!');
	} catch (error) {
		console.error('❌ 배포 중 오류가 발생했습니다:', error.message);
		throw error;
	}
}

/**
 * 메인 실행 함수
 */
function main() {
	try {
		console.log('🚀 GitHub 패키지 배포 시작...');

		// 1. Git 상태 확인
		checkGitStatus();

		// 2. 현재 버전 확인
		const currentVersion = getCurrentVersion();
		console.log(`📋 현재 버전: ${currentVersion}`);

		// 3. 버전 증가 (npm version 명령어 사용)
		const newVersion = incrementVersion();
		console.log(`✅ 새 버전: ${newVersion}`);

		// 4. 패키지 준비 (Prisma 빌드 + enum 업데이트 + 빌드)
		console.log('🔨 패키지 준비 중...');
		execSync('npm run package', { stdio: 'inherit' });

		// 5. TypeScript 선언 파일 이름 변경
		renameDeclarationFile();

		// 6. 빌드 검증
		verifyBuild();

		// 7. 배포 실행
		publishPackage();

		console.log(`🎉 @timbel-timblo-onpremise/prisma v${newVersion} 배포 완료!`);
		console.log(`📦 패키지 URL: ${GITHUB_REGISTRY}@timbel-timblo-onpremise/prisma`);
		process.exit(0);
	} catch (error) {
		console.error('❌ 배포 실패:', error.message);
		process.exit(1);
	}
}

// 스크립트 실행
main();
