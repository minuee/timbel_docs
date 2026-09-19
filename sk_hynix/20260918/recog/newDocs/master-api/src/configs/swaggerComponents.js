const securitySchemes = {
	sessionAuth: {
		type: 'apiKey',
		in: 'cookie',
		name: 'connect.sid',
		description: '세션 쿠키를 통한 인증 (자동 전송)',
	},
	bearerAuth: {
		type: 'http',
		scheme: 'bearer',
		bearerFormat: 'JWT',
		description: 'JWT 토큰을 통한 인증',
	},
	timbloTokenAuth: {
		type: 'apiKey',
		in: 'header',
		name: 'x-timblo-token',
		description: 'Gateway 없는 환경에서 테스트용 토큰 (localhost에서만 사용)',
	},
};

const Error = {
	type: 'object',
	properties: {
		httpCode: {
			type: 'integer',
			example: 500,
		},
		message: {
			type: 'string',
			example: 'Internal Server Error',
		},
		errorCode: {
			type: 'string',
			example: 'E0500',
		},
		result: {
			type: 'object',
			nullable: true,
		},
	},
};

const Success = {
	type: 'object',
	properties: {
		httpCode: {
			type: 'integer',
			example: 200,
		},
		message: {
			type: 'string',
			example: 'Success',
		},
		data: {
			type: 'object',
			nullable: true,
		},
	},
};

export default {
	securitySchemes,
	schemas: {
		Error,
		Success,
	},
};
