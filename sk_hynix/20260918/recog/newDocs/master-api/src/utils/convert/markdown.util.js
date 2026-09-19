import MarkdownIt from 'markdown-it';

export const md = new MarkdownIt({
	html: true,
	linkify: true,
	typographer: true,
	breaks: true,
});

class MarkdownUtil {
	convertSummaryToHtml(summary) {
		if (!summary || typeof summary !== 'string') return '';

		md.renderer.rules.heading_open = function (tokens, idx) {
			const level = tokens[idx].tag;
			if (level === 'h3') {
				return `<h3 style="color: #005cff; margin: 0 0 15px 0; font-weight: 700;">`;
			}
			return `<${level}>`;
		};

		md.renderer.rules.bullet_list_open = function () {
			return '<ul style="margin: 10px 0; padding-left: 20px;">';
		};

		md.renderer.rules.list_item_open = function () {
			return '<li style="margin: 5px 0;">';
		};

		md.renderer.rules.text = function (tokens, idx) {
			let text = tokens[idx].content;
			text = text.replace(/\[(북마크|메모|태스크|알림)\]/g, '<strong>[$1]</strong>');
			return text;
		};

		return md.render(summary);
	}
}

export default new MarkdownUtil();
