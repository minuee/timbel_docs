class TimeUtil {
	//ex) 3559 ms  -->  00:00:03,  11333559 ms  --> 03:08:53
	timeFormat(ms) {
		let seconds = ms / 1000;
		let hours = parseInt(seconds / 3600);
		seconds = seconds % 3600;
		let minutes = parseInt(seconds / 60);
		seconds = seconds % 60;
		hours = `0${Math.floor(hours)}`.slice(-2);
		minutes = `0${Math.floor(minutes)}`.slice(-2);
		seconds = `0${Math.floor(seconds)}`.slice(-2);
		return `${hours}:${minutes}:${seconds}`;
	}

	//ex) 3559 ms   --> 00:03,  11333559 ms  --> 03:08:53
	convertTimeFormat(milliseconds) {
		let seconds = Math.floor(milliseconds / 1000);
		let minutes = Math.floor(seconds / 60);
		let hours = Math.floor(minutes / 60);

		seconds = seconds % 60;
		minutes = minutes % 60;

		const pad = num => num.toString().padStart(2, '0');

		if (hours > 0) {
			return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
		} else {
			return `${pad(minutes)}:${pad(seconds)}`;
		}
	}
}

export default new TimeUtil();
