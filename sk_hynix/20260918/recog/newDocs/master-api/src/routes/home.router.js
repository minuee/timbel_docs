import express from 'express';
import homeController from '../controller/user/home.controller.js';

const router = express.Router();

router.get('/', homeController.getDashboard);

export default router;
