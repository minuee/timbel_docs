import os from 'os';
import http from 'http';
import Consul from 'consul';

// 스마트 IP 탐지 로직
const getServiceIp = () => {
	if (process.env.CHECK_IP) return process.env.CHECK_IP;
	const ips = Object.values(os.networkInterfaces())
		.flat()
		.filter(details => details.family === 'IPv4' && !details.internal)
		.map(details => details.address);
	return (
		ips.find(ip => ip.startsWith('192.168.')) ||
		ips.find(ip => ip.startsWith('10.')) ||
		ips.find(ip => ip.startsWith('172.')) ||
		ips[0] ||
		'127.0.0.1'
	);
};

const ip = getServiceIp();
const port = Number(process.env.PORT);
const app = process.env.SYS_NAME;
const instance = `${app}-${process.env.INSTANCE_ID ?? '0'}`;

const useTtlCheck = process.env.USE_CONSUL_TTL_CHECK === 'true'; // TTL 헬스체크 사용 여부
const ttlCheckId = `service:${instance}`;

let heartbeatTimer;
let reRegisterTimer;
let isRegistering = false;

// Heartbeat 타이머 정리 유틸리티
const stopHeartbeat = () => {
	if (!heartbeatTimer) return;
	clearInterval(heartbeatTimer);
	heartbeatTimer = null;
};

// Consul 클라이언트 & KV Watcher 초기화
const consul = new Consul({
	host: process.env.CONSUL_HOST || 'consul-discovery',
	port: process.env.CONSUL_PORT || 8500,
	secure: false,
});

const watcher = consul.watch({
	method: consul.kv.get,
	options: { key: 'timblo/master/mutable' },
});

const watcherMinio = consul.watch({
	method: consul.kv.get,
	options: { key: 'timblo/common/credentials' },
});

const parseWatcherAndEmit = (Value, event = 'configChanged') => {
	if (!Value) return;
	try {
		Value = Value.replace(/,\s*}$/, '}');
		const configValues = JSON.parse(Value);
		Object.keys(configValues).forEach(key => {
			process.env[key] = configValues[key];
		});
		process.emit(event);
		log.i('설정 값이 변경되었습니다');
	} catch (e) {
		log.e('Watcher 설정 파싱 실패:', e.message);
	}
};

watcher.on('change', ({ Value }) => parseWatcherAndEmit(Value));
watcherMinio.on('change', ({ Value }) => parseWatcherAndEmit(Value, 'storageChanged'));
watcher.on('error', err => log.e('Consul watcher error:', err.message));
watcherMinio.on('error', err => log.e('Consul watcherMinio error:', err.message));

// ==========================================
// Self-Health Check 메서드
// ==========================================
const checkLocalHttpHealth = () =>
	new Promise(resolve => {
		let resolved = false;

		const safeResolve = value => {
			if (resolved) return;
			resolved = true;
			resolve(value);
		};

		const req = http.get(
			{
				host: '127.0.0.1',
				port: port,
				path: '/health',
				timeout: 1000, // 1초 타임아웃
			},
			res => {
				res.resume();
				safeResolve(res.statusCode === 200);
			}
		);

		req.on('error', () => {
			safeResolve(false);
		});

		req.on('timeout', () => {
			req.destroy();
			safeResolve(false);
		});
	});

// ==========================================
// Heartbeat (TTL) 로직
// ==========================================
const startHeartbeat = () => {
	stopHeartbeat();

	heartbeatTimer = setInterval(async () => {
		try {
			const isHealthy = await checkLocalHttpHealth(); // 자가 진단
			try {
				if (isHealthy) {
					await consul.agent.check.pass(ttlCheckId); // 성공 시: Consul에게 Pass 신호 전송 (TTL 연장)
				} else {
					await consul.agent.check.fail(ttlCheckId); // 실패 시: Fail 신호 전송 (트래픽 차단)
				}
			} catch (checkErr) {
				log.w(`Heartbeat 체크 전송 실패 (check_id: ${ttlCheckId}):`, checkErr.message);
				log.w('Agent API 접근 확인 필요. 네트워크 경로 및 Consul의 Agent API 노출여부 확인 필요');
			}
		} catch (e) {
			log.e('Heartbeat 중 오류 발생, 다음 주기에 재시도:', e.message);
		}
	}, 15000); // 15초마다 생존 신호 (TTL의 절반)
};

// ==========================================
// 서비스 등록 및 복구 (Core Logic)
// ==========================================
const registerService = async () => {
	stopHeartbeat();
	try {
		log.i(`서비스 등록 시도: ${instance} (${ip}:${port})`);

		const checkConfig =
			useTtlCheck ?
				{
					id: ttlCheckId,
					name: 'ttl',
					ttl: process.env.CONSUL_TTL || '30s',
					deregistercriticalserviceafter: process.env.CONSUL_DEREGISTER_AFTER || '1m',
				}
			:	{
					http: `http://${ip}:${port}/health`,
					interval: '10s',
					timeout: '5s',
					deregistercriticalserviceafter: process.env.CONSUL_DEREGISTER_AFTER || '1m',
				};

		await consul.agent.service.register({
			name: app,
			id: instance,
			address: ip,
			port: port,
			check: checkConfig,
		});

		if (useTtlCheck) startHeartbeat();
		log.i(`${app}가 Consul에 ${useTtlCheck ? '⏳TTL' : '🌐HTTP'} 체크로 등록 완료: ${instance} (${ip}:${port})`);

		reRegisterTimer = setInterval(ensureRegistration, 30000); // 30초 주기로 자가 복구 모니터링
		log.i('서비스 디스커버리 재등록 모니터링 활성화됨');
	} catch (err) {
		log.e('서비스 등록 중 오류 발생, 다음 주기에 재시도:', err.message);
		throw err;
	}
};

// 서비스 등록 및 복구 메서드
const ensureRegistration = async () => {
	if (isRegistering) return;
	isRegistering = true;

	try {
		const nodes = await consul.catalog.service.nodes(app);
		const myNode = nodes.find(node => node.ServiceID === instance);
		if (!myNode || myNode.ServicePort !== port) {
			log.w(`서비스가 Consul에 누락되었습니다. 재등록 시도: ${instance} (${ip}:${port})`);
			await registerService();
		}
	} catch (e) {
		log.e('서비스 등록 중 오류 발생, 다음 주기에 재시도:', e.message);
	} finally {
		isRegistering = false;
	}
};

const deregisterService = async () => {
	if (reRegisterTimer) clearInterval(reRegisterTimer);
	stopHeartbeat();

	try {
		await consul.agent.service.deregister(instance);
		log.i(`${app} 서비스가 Consul에서 등록 해제되었습니다.`);
	} catch (err) {
		log.e('서비스 등록 해제 중 오류 발생:', err.message);
	}
};

const healthChecker = (req, res) => {
	res.status(200).send('ok');
};

export default { consul, registerService, deregisterService, healthChecker };
