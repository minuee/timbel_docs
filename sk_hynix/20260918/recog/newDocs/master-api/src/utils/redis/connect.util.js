import Redis from 'ioredis';

export const createRedisCluster = () => {
	const { REDIS_CLUSTER_HOSTS, REDIS_CLUSTER_PASSWORD } = process.env;
	const hosts = REDIS_CLUSTER_HOSTS.split(',');
	const parsedHosts = hosts.map(host => {
		const [ip, port, password = REDIS_CLUSTER_PASSWORD] = host.split(':');
		return { host: ip, port: parseInt(port), password };
	});
	log.i('[RedisClusterConfig]', parsedHosts);
	return new Redis.Cluster(parsedHosts);
};

export const createLegacyRedisClientConfig = () => {
	const { REDIS_HOST, REDIS_PORT, REDIS_PASS } = process.env;
	const config = {
		redis: {
			host: REDIS_HOST,
			port: REDIS_PORT,
			password: REDIS_PASS,
		},
	};
	log.i('[RedisStandaloneConfig]', config);
	return config;
};

export const isRedisCluster = () => {
	return process.env.REDIS_CLUSTER_HOSTS ? true : false;
};

export default { createRedisCluster, createLegacyRedisClientConfig, isRedisCluster };
