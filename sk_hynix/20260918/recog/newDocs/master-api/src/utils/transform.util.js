class TransformUtil {
	transformTemplates(templates) {
		const groupedByCategory = templates.reduce((acc, template) => {
			const categoryId = template.category?.id || 'DEFAULT-CATEGORY';
			const categoryName = template.category?.name || '기본 템플릿';

			const { category, favorites, ...templateData } = template;
			const isFavorite = favorites.length > 0;

			if (!acc[categoryId]) {
				acc[categoryId] = {
					categoryId,
					name: categoryName,
					templates: [],
				};
			}

			acc[categoryId].templates.push({ ...templateData, isFavorite });
			return acc;
		}, {});

		return Object.values(groupedByCategory).sort((a, b) => a.name.localeCompare(b.name, 'ko'));
	}

	transformCalendarWithContentMap(calendarContents, contentsResponse) {
		const contentMap = new Map(contentsResponse.map(content => [content.contentId, content]));

		return calendarContents.map(calendar => {
			if (!calendar.content) {
				return {
					...calendar,
					content: null,
				};
			}

			const content = contentMap.get(calendar.content?.contentId);
			return {
				...calendar,
				content: {
					...content,
					isShared: content.shareUsers.length > 0,
				},
			};
		});
	}
}

export default new TransformUtil();
