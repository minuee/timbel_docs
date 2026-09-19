class ParserUtil {
	summaryResponse(summaryResponses) {
		let ai = {};
		let summaryTime = [];
		Object.keys(summaryResponses).forEach(key => {
			if (key.includes('summary-')) {
				if (key.includes('summary-time')) {
					summaryTime = summaryResponses[key].map(item => {
						const { speakerSummary } = item;
						if (speakerSummary) {
							item['summary'].push(...speakerSummary);
							delete item['speakerSummary'];
						}
						return item;
					});
				} else summary.push(summaryResponses[key]);
			} else {
				ai = summaryResponses[key] ?? {};
			}
		});
		return { ai, summaryTime };
	}

	jsonBigintToInt(obj) {
		return JSON.parse(
			JSON.stringify(obj, (_, value) => (typeof value === 'bigint' ? Number(value.toString()) : value))
		);
	}
}

export default new ParserUtil();
