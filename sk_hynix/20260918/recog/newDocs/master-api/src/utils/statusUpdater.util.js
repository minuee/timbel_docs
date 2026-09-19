import notify from './notify.util.js';

class statusUpdater {
	constructor(params, member) {
		this.params = params;
		this.member = member;
	}

	call(status) {
		return notify.sttStatus({ status }, this.params, this.member);
	}
}

export default statusUpdater;
