import express from 'express';
import integrateController from '../controller/engine/integrate.controller.js';

const router = express.Router();

router.post('/summary', integrateController.segmentToSummary);

export default router;
