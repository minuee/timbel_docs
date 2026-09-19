class StringUtil {
	originalnameEncoding({ originalname }) {
		return Buffer.from(originalname, 'latin1').toString('utf8');
	}

	keywordTransform(keyword) {
		return keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	}
}

export default new StringUtil();
