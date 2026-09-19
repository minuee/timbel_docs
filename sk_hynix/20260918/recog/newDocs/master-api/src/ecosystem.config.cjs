/* eslint-disable camelcase */
require('dotenv').config();

console.log('RECOG_WORKER', process.env.RECOG_WORKER);
module.exports = {
	apps: [
		{
			name: 'timblo-master-service',
			script: './app.js',
			instances: `${process.env.RECOG_WORKER ?? 3}`,
			exec_mode: 'cluster',
			instance_var: 'INSTANCE_ID',
		},
	],
};
