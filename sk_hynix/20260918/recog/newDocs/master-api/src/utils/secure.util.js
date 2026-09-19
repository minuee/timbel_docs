import fs from 'fs';
import path from 'path';
import crypto from 'crypto-js';
import cryptoV1 from 'crypto';
import { pipeline } from 'node:stream/promises';
import generate from './generate.util.js';

const { env } = process;
class SecureUtil {
	encryptAes(data) {
		const SECRET_KEY = env.ENCRYPT_SECRET_KEY || undefined;
		return crypto.AES.encrypt(data, SECRET_KEY).toString();
	}

	decryptAes(data) {
		const SECRET_KEY = env.ENCRYPT_SECRET_KEY || undefined;
		const bytes = crypto.AES.decrypt(data, SECRET_KEY);
		const decryptedText = bytes.toString(crypto.enc.Utf8);
		return decryptedText;
	}

	async decryptFilesAesCbc(filePath, inputFiles, outputFileName) {
		const SECRET_KEY = Buffer.from(process.env.AES_KEY, 'utf8');
		const IV = Buffer.from(process.env.AES_IV, 'utf8');
		const outputFilePath = path.join(filePath, `${outputFileName}_decrypted.pcm`);
		const startTime = Date.now();

		for (const file of inputFiles) {
			await pipeline(
				fs.createReadStream(path.join(filePath, file)),
				cryptoV1.createDecipheriv('aes-256-cbc', SECRET_KEY, IV),
				fs.createWriteStream(outputFilePath, { flags: 'a' })
			);
		}
		const duration = (Date.now() - startTime) / 1000;
		log.i(
			`[SecureUtil : decryptFilesAesCbc] decrypted convert time : ${outputFilePath} / ${duration.toFixed(2)} sec`
		);
		return outputFilePath;
	}

	encryptECB = data => {
		const SECRET_KEY = process.env.ENCRYPT_SECRET_KEY || undefined;
		const keyHex = generate.keyFromString(SECRET_KEY, 'hex');
		const keyBuffer = Buffer.from(keyHex, 'hex');
		const cipher = cryptoV1.createCipheriv('aes-256-ecb', keyBuffer, '');
		let encrypted = cipher.update(data, 'utf8', 'hex');
		encrypted += cipher.final('hex');
		return encrypted;
	};
}

export default new SecureUtil();
