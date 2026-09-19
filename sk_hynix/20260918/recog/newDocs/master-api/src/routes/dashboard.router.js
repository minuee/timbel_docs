import express from 'express';
import dashboardController from '../controller/user/dashboard.controller.js';

const router = express.Router();

router.get('/', dashboardController.getDashboard);

export default router;
