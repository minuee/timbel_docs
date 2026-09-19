import fs from 'fs';
import 'dotenv/config';
import path from 'path';
import Consul from 'consul';

const envFilePath = path.join(process.cwd(), '.env');
const consul = new Consul({
	host: process.env.CONSUL_HOST || 'consul-discovery',
	port: process.env.CONSUL_PORT || 8500,
	secure: false,
});

console.log('envFilePath:', envFilePath);

const MAX_RETRIES = process.env.FETCH_ENV_MAX_RETRIES || 20;
const RETRY_DELAY = process.env.FETCH_ENV_RETRY_DELAY || 5000;

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

const getConfigJson = async () => {
	let commonConfig = await consul.kv.get('timblo/common/env');
	if (!commonConfig) throw new Error('No config found in Consul common/env');
	const value2 = commonConfig.Value.replace(/,\s*}$/, '}');
	commonConfig = JSON.parse(value2);

	let immutableConfig = await consul.kv.get(`timblo/${process.env.APP_NAME}/immutable`);
	if (!immutableConfig) {
		immutableConfig = {};
		await consul.kv.set(`timblo/${process.env.APP_NAME}/immutable`, JSON.stringify(immutableConfig));
		console.log(`Set empty immutable config to Consul: timblo/${process.env.APP_NAME}/immutable`);
	} else {
		const value = immutableConfig.Value.replace(/,\s*}$/, '}');
		immutableConfig = JSON.parse(value);
	}

	return { ...immutableConfig, ...commonConfig };
};

const writeEnvFile = config => {
	let envContent = '';
	Object.keys(config).forEach(key => {
		let value = config[key];
		if (isNaN(value) || typeof value === 'string') {
			value = `"${value}"`;
		}
		envContent += `${key}=${value}\n`;
	});

	fs.writeFileSync(envFilePath, envContent);
	console.log('.env file created successfully');
};

const fetchEnvWithRetry = async (retryCount = 0) => {
	try {
		const config = await getConfigJson();
		writeEnvFile(config);
	} catch (err) {
		if (retryCount < MAX_RETRIES) {
			const nextRetry = retryCount + 1;
			console.error(`Error generating .env file (attempt ${nextRetry}/${MAX_RETRIES}):`, err.message);
			console.log(`Retrying in ${RETRY_DELAY}ms...`);
			await sleep(RETRY_DELAY);
			return fetchEnvWithRetry(nextRetry);
		} else {
			console.error(`Error generating .env file after ${MAX_RETRIES} attempts:`, err.message);
			process.exit(1);
		}
	}
};

fetchEnvWithRetry();
