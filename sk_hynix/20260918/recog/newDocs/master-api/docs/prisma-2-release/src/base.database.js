/**
 * @fileoverview Timblo Prisma Database Module
 * @version 0.0.2
 * @author timbel
 */
import '@baronote/logger';
import {
	PrismaClient as mariaPrisma,
	CalendarProvider,
	IntegrateType,
	YesNo,
	CorrectionStatus,
	ContentType,
	ContentShareRole,
	DownloadType,
	DownloadDevice,
	DownloadDeviceMobile,
	ReSummarySize,
	MemoItem,
	MethodType,
	NotifyType,
	UsageType,
	DomainType,
	AdminType,
	MenuGroup,
	TermsStatus,
	AgreementStatus,
	PolicyCategory,
	PolicyStatus,
	BatchType,
	BatchStatus,
	Provider,
	SupportLang,
	Engine,
	Summarizer,
	OS,
	LoginDevice,
	UserNotificationChannel,
	UserNotificationEventType,
	TotpActionType,
	TotpResultType,
	WorkspaceRole,
	PlatformType,
	PermissionType,
	PolicyType,
	Unit,
	SettingValueType,
	WorkspaceSettingUiType,
	WorkspaceSettingGroup,
} from './libs/prismaService/mariaDB/index.js';
import {
	PrismaClient as mongoPrisma,
	BookmarksKeys,
	MemoKeys,
	TranslateType,
} from './libs/prismaService/mongoDB/index.js';

const prismaLogConfig = [
	{
		emit: 'event',
		level: 'query',
	},
	{
		emit: 'event',
		level: 'error',
	},
];

const ContentFilter = {
	ALL: 'all',
	OWNED: 'owned',
	SHARED_IN: 'sharedIn',
	SHARED_OUT: 'sharedOut',
};

const Enums = {
	// MariaDB Enums
	CalendarProvider,
	IntegrateType,
	YesNo,
	CorrectionStatus,
	ContentType,
	ContentShareRole,
	DownloadType,
	DownloadDevice,
	DownloadDeviceMobile,
	ReSummarySize,
	MemoItem,
	MethodType,
	NotifyType,
	UsageType,
	DomainType,
	AdminType,
	MenuGroup,
	TermsStatus,
	AgreementStatus,
	PolicyCategory,
	PolicyStatus,
	BatchType,
	BatchStatus,
	Provider,
	SupportLang,
	Engine,
	Summarizer,
	OS,
	LoginDevice,
	UserNotificationChannel,
	UserNotificationEventType,
	TotpActionType,
	TotpResultType,
	WorkspaceRole,
	PlatformType,
	PermissionType,
	PolicyType,
	Unit,
	SettingValueType,
	WorkspaceSettingUiType,
	WorkspaceSettingGroup,

	// MongoDB Enums
	BookmarksKeys,
	MemoKeys,
	TranslateType,

	// Custom Enums
	ContentFilter,
};

class BaseDatabase {
	constructor(className) {
		this.className = className ?? 'unknown';

		this.mariaDB = new mariaPrisma({ log: prismaLogConfig });
		this.mongoDB = new mongoPrisma({
			log: prismaLogConfig,
			transactionOptions: {
				maxWait: 5000,
				timeout: 60000,
			},
		});

		// 개발 환경에서는 추가 로깅 활성화
		if (process.env.NODE_ENV === 'development') {
			this.queryEventHandler();
			this.errorEventHandler();
		}
	}

	queryEventHandler() {
		this.mariaDB.$on('query', ({ duration, query }) => {
			log.s(`[mariaDB : ${this.className} : ${duration}ms] : ${query}\n`);
		});

		this.mongoDB.$on('query', ({ duration, query }) => {
			log.s(`[mongoDB : ${this.className} : ${duration}ms] : ${query}\n`);
		});
	}

	errorEventHandler() {
		this.mariaDB.$on('error', ({ message }) => {
			log.e(`[mariaDB : ${this.className}] : ${message}`);
		});

		this.mongoDB.$on('error', ({ message }) => {
			log.e(`[mongoDB : ${this.className}] : ${message}`);
		});
	}

	Enums = Enums;
}

/**
 * @typedef {Object} Enums
 * @property {Object} YesNo - MariaDB YesNo enum
 * @property {Object} CorrectionStatus - MariaDB CorrectionStatus enum
 * @property {Object} ContentType - MariaDB ContentType enum
 * @property {Object} ContentShareRole - MariaDB ContentShareRole enum
 * @property {Object} DownloadType - MariaDB DownloadType enum
 * @property {Object} DownloadDevice - MariaDB DownloadDevice enum
 * @property {Object} DownloadDeviceMobile - MariaDB DownloadDeviceMobile enum
 * @property {Object} ReSummarySize - MariaDB ReSummarySize enum
 * @property {Object} NotifyType - MariaDB NotifyType enum
 * @property {Object} UsageType - MariaDB UsageType enum
 * @property {Object} DomainType - MariaDB DomainType enum
 * @property {Object} TermsStatus - MariaDB TermsStatus enum
 * @property {Object} AgreementStatus - MariaDB AgreementStatus enum
 * @property {Object} PolicyCategory - MariaDB PolicyCategory enum
 * @property {Object} BatchType - MariaDB BatchType enum
 * @property {Object} BatchStatus - MariaDB BatchStatus enum
 * @property {Object} Provider - MariaDB Provider enum
 * @property {Object} SupportLang - MariaDB SupportLang enum
 * @property {Object} Engine - MariaDB Engine enum
 * @property {Object} Summarizer - MariaDB Summarizer enum
 * @property {Object} OS - MariaDB OS enum
 * @property {Object} LoginDevice - MariaDB LoginDevice enum
 * @property {Object} WorkspaceRole - MariaDB WorkspaceRole enum
 * @property {Object} PlatformType - MariaDB PlatformType enum
 * @property {Object} PermissionType - MariaDB PermissionType enum
 * @property {Object} PolicyType - MariaDB PolicyType enum
 * @property {Object} Unit - MariaDB Unit enum
 * @property {Object} SettingValueType - MariaDB SettingValueType enum
 * @property {Object} WorkspaceSettingUiType - MariaDB WorkspaceSettingUiType enum
 * @property {Object} WorkspaceSettingGroup - MariaDB WorkspaceSettingGroup enum
 * @property {Object} BookmarksKeys - MongoDB BookmarksKeys enum
 * @property {Object} MemoKeys - MongoDB MemoKeys enum
 * @property {Object} MongoYesNo - MongoDB YesNo enum
 * @property {Object} TranslateType - MongoDB TranslateType enum
 * @property {Object} MongoSupportLang - MongoDB SupportLang enum
 * @property {Object} MongoEngine - MongoDB Engine enum
 * @property {Object} ContentFilter - Custom ContentFilter enum
 */

/**
 * @typedef {Object} PrismaClients
 * @property {import('@prisma/client').PrismaClient} mariaDB - MariaDB Prisma Client
 * @property {import('@prisma/client').PrismaClient} mongoDB - MongoDB Prisma Client
 */

/**
 * BaseDatabase 클래스
 * @class
 * @param {string} [className='unknown'] - 클래스 이름
 * @property {PrismaClients} mariaDB - MariaDB Prisma Client 인스턴스
 * @property {PrismaClients} mongoDB - MongoDB Prisma Client 인스턴스
 * @property {Enums} Enums - 모든 Enum 값들
 */
export default BaseDatabase;

/**
 * 모든 Enum 값들을 포함한 객체
 * @type {Enums}
 */
export { Enums };
