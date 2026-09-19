// prettier-ignore
import { 
    cors, 
    express, 
    discovery, 
	telemetry,
    cookieParser, 
    morganMiddleware, 
} from './app.module.js';
import './app.handle.js';
import homeRouter from './routes/home.router.js';
import userRouter from './routes/user.router.js';
import dashboardRouter from './routes/dashboard.router.js';
import inboxRouter from './routes/inbox.router.js';
import queueRouter from './routes/queue.router.js';
import noticeRouter from './routes/notice.router.js';
import searchRouter from './routes/search.router.js';
import contentRouter from './routes/content.router.js';
import chatbotRouter from './routes/chatbot.router.js';
import keywordRouter from './routes/keyword.router.js';
import ErrorHandler from './handlers/error.handler.js';
import calendarRouter from './routes/calendar.router.js';
import templateRouter from './routes/template.router.js';
import bookmarkRouter from './routes/bookmark.router.js';
import integrateRouter from './routes/integrate.router.js';
import authorizeMember from './handlers/authorize.handler.js';
import { swaggerUi, specs, uiOptions } from './configs/swagger.js';
import authenticateRequest from './handlers/authenticate.handler.js';
import setupBullBoard from './configs/bull-board.config.js';

const app = express();

if (process.env.NODE_ENV !== 'production') {
	app.use('/api-docs', swaggerUi.serve, swaggerUi.setup(specs, uiOptions));
	await setupBullBoard()
		.then(serverAdapter => {
			if (serverAdapter) {
				app.use(`/admin/queues`, serverAdapter.getRouter());
				log.i('[App] Bull Board initialized at /admin/queues');
			}
		})
		.catch(err => {
			log.e('[App] Error initializing Bull Board:', err.message);
		});
}

app.use(telemetry.traceMiddleware());

app.use('/health', discovery.healthChecker);

app.use(
	express.json({
		limit: '1gb',
	})
);

app.use(
	express.urlencoded({
		limit: '1gb',
		extended: false,
	})
);

// set middleware
app.use(cookieParser());
app.use(morganMiddleware(app));
app.use(cors({ origin: true, credentials: true }));

const server = app.listen(process.env.PORT ?? 9010, '0.0.0.0', async () => {
	log.i(`Listening on ${process.env.PORT}`);
	await discovery.registerService();
});

// 대용량 파일 업로드 수신을 위해 Node 기본 requestTimeout(5분)을 상향한다.
// 앱 업로드 타이머(UPLOAD_TIMEOUT, 기본 consul KV)보다 살짝 크게 두어 하드 백스톱으로 동작 → 업로드 타이머가 먼저 로그를 남긴다.
// env 우선(consul KV가 정본), 미설정 시 31분.
const applyRequestTimeout = () => {
	server.requestTimeout = Number(process.env.HTTP_REQUEST_TIMEOUT_MS) || 31 * 60 * 1000;
};
applyRequestTimeout();
process.on('configChanged', applyRequestTimeout);

app.use(authenticateRequest);
app.use(authorizeMember);

app.use('/home', homeRouter);
app.use('/dashboard', dashboardRouter);
app.use('/user', userRouter);
app.use('/search', searchRouter);
app.use('/contents', contentRouter);
app.use('/inbox', inboxRouter);
app.use('/bookmark', bookmarkRouter);
app.use('/integrate', integrateRouter);
app.use('/queue', queueRouter);
app.use('/notice', noticeRouter);
app.use('/chat', chatbotRouter);
app.use('/calendar', calendarRouter);
app.use('/template', templateRouter);
app.use('/keyword', keywordRouter);

app.use(ErrorHandler.exception);

process.once('SIGINT', async () => {
	await discovery.deregisterService();
	log.i(`${process.env.SYS_NAME} is stopped`);
	process.exit(0);
});

export default app;
