import swaggerJsdoc from 'swagger-jsdoc';
import swaggerUi from 'swagger-ui-express';
import components from './swaggerComponents.js';

const info = {
	title: 'Timblo Master Service API',
	version: '1.0.0',
	description: 'Timblo 마스터 서비스 API 문서',
	contact: {
		name: 'inc. timbel',
		email: 'jwpark@timbel.net',
	},
};

const servers = [
	{
		url: 'http://localhost:9010',
		description: 'Local Server',
	},
	{
		url: 'https://dev.timblo.io/api',
		description: 'Timblo Development Server',
	},
];

const security = [
	{
		bearerAuth: [],
	},
	{
		timbloTokenAuth: [],
	},
	{
		sessionAuth: [],
	},
];

const options = {
	definition: {
		openapi: '3.0.0',
		info,
		servers,
		security,
		components,
	},
	apis: ['./docs/schemas/*.js', './docs/routes/*.js'],
};

const uiOptions = {
	explorer: true,
	customCss: '.swagger-ui .topbar { display: none }',
	customSiteTitle: 'Timblo Master Service API',
	swaggerOptions: {
		persistAuthorization: true,
		withCredentials: true,
		requestInterceptor: req => {
			req.credentials = 'include';
			return req;
		},
	},
};
const specs = swaggerJsdoc(options);

export { swaggerUi, specs, uiOptions };
