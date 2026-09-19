class JsonUtil {
	contentToJson({ tag }, content) {
		try {
			const regex = /^\`\`\`json(\n)?|\`\`\`(\n)?$/g;
			return { [tag]: JSON.parse(content.replace(regex, '')) };
		} catch (err) {
			return { [tag]: content };
		}
	}

	contentToJsonV2SummaryOnly(content) {
		try {
			const regex = /^\`\`\`json(\n)?|\`\`\`(\n)?$/g;
			const regex2 = /<\/?output_format>/g;
			return { ...JSON.parse(content.replace(regex, '').replace(regex2, '')) };
		} catch (err) {
			return { ...content };
		}
	}
}

export default new JsonUtil();
