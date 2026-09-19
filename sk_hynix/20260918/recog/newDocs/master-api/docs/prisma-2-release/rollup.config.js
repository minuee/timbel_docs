import { defineConfig } from 'rollup';
import { nodeResolve } from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// package.json에서 버전 정보 읽기
const packageJson = JSON.parse(readFileSync(join(__dirname, 'package.json'), 'utf8'));

export default defineConfig([
	// ESM 빌드 (난독화 없음)
	{
		input: 'src/base.database.js',
		output: {
			file: 'dist/index.esm.js',
			format: 'esm',
			banner: `/* @timbel-timblo-onpremise/prisma v${packageJson.version} */`,
		},
		plugins: [
			nodeResolve({
				preferBuiltins: false,
			}),
			commonjs(),
		],
		external: [
			'@baronote/logger',
			'@prisma/client',
			'./libs/prismaService/mariaDB/index.js',
			'./libs/prismaService/mongoDB/index.js',
		],
	},
	// CommonJS 빌드 (난독화 없음)
	{
		input: 'src/base.database.js',
		output: {
			file: 'dist/index.cjs',
			format: 'cjs',
			banner: `/* @timbel-timblo-onpremise/prisma v${packageJson.version} */`,
		},
		plugins: [
			nodeResolve({
				preferBuiltins: false,
			}),
			commonjs(),
		],
		external: [
			'@baronote/logger',
			'@prisma/client',
			'./libs/prismaService/mariaDB/index.js',
			'./libs/prismaService/mongoDB/index.js',
		],
	},
]);
