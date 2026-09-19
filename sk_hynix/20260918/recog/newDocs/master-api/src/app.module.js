import 'dotenv/config';
import cors from 'cors';
import express from 'express';
import session from 'express-session';
import cookieParser from 'cookie-parser';
import { morganMiddleware } from '@baronote/logger';
import discovery from './configs/discovery-config.js';
import telemetry from '@timbel-timblo-onpremise/tracely';
import lifecycleInit from './handlers/lifecycle.handler.js';

export { cookieParser, cors, discovery, express, morganMiddleware, session, telemetry, lifecycleInit };
