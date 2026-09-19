import express from 'express';
import calendarController from '../controller/feature/calendar.controller.js';

const router = express.Router();

router.get('/', calendarController.getCalendars);
router.post('/', calendarController.createCalendar);
router.delete('/:id', calendarController.deleteCalendar);
router.put('/:id', calendarController.updateCalendar);

router.get('/integrate/', calendarController.getIntegrateCalendars);

router.post('/integrate/sync', calendarController.syncIntegrate);
router.post('/integrate/webcal', calendarController.connectWebcal);
router.post('/integrate/load', calendarController.loadIntegrate);

router.get('/integrate/settings', calendarController.getIntegrateSettings);

router.delete('/integrate/disconnect/:provider', calendarController.disconnectWebcal);

export default router;
