process.on('uncaughtException', err => {
	log.e('[uncaughtException] : ', err.message);
	process.exit(1);
});

process.on('error', err => {
	log.e('[error] : ', err.message);
	process.exit(1);
});
