export const prompts = [
	{
		tag: 'ai',
		text: `
You are tasked with analyzing a meeting transcript and generating both a detailed summary and an overall summary. The meeting transcript will be provided in the following JSON format:

[
  {
    "speaker": "1",
    "time": "00:00:01",
    "content": "Speech content"
  },
  {
    "speaker": "2",
    "time": "00:02:42",
    "content": "Speech content"
  },
  ...
]

Here is the meeting transcript:

<body>
{{MEETING_TRANSCRIPT}}
</body>

First, generate a detailed summary of the meeting. Follow these steps:

1. Divide the transcript into logical segments based on subtopics or time intervals.
   - [Strict Rule] Ensure that every segment includes all content up to the end of its specified time range.
2. For each segment, create an entry with the following information:
   - index: Assign a sequential number to each segment
   - time: Provide the start and end time of the segment in the format "startTime~endTime"
   - subtopics: Write a brief subtitle for the segment
   - content: Summarize the main points of the segment in 3 bullet points
   - speaker_summary: Summarize the key points made by each speaker in this segment

Next, generate an overall summary of the entire meeting. Include the following elements:

1. 주제 (Topic): Identify the main topic or purpose of the meeting
2. 이슈 사항 (Issues): List any significant issues or problems discussed
3. 요약 (Summary): Provide a concise summary of the entire meeting
4. 할 일 (Tasks): List any action items or tasks assigned during the meeting
5. 키워드 (Keywords): Identify 3-5 key terms or phrases that capture the essence of the meeting
6. 발화자별 요약 (Speaker Summary): Provide a summary of key points made by each speaker throughout the entire meeting

Present your output in JSON format, structured as follows:

<output_format>
{
  "summary-time-details": [
    {
      "index": 1,
      "time": "startTime~endTime",
      "topic": "소제목",
      "summary": [
        "요약1",
        "요약2",
        "요약3"
      ],
      "speakerSummary": [
        "발화자1 : 발화자1의 주요 내용",
        "발화자2 : 발화자2의 주요 내용"
      ]
    },
    {
      "index": 2,
      "time": "startTime~endTime",
      "topic": "소제목",
      "summary": [
        "요약1",
        "요약2",
        "요약3"
      ],
      "speakerSummary": [
        "발화자1 : 발화자1의 주요 내용",
        "발화자2 : 발화자2의 주요 내용"
      ]
    }
  ],
  "ai": {
    "topics": ["회의의 주요 주제"],
    "keywords": [
      "키워드1",
      "키워드2",
      "키워드3"
    ],
    "summary": ["전체 회의 내용 요약"],
    "tasks": [
      "할 일1",
      "할 일2",
      "할 일3"
    ],
    "issues": [
      "이슈1",
      "이슈2",
      "이슈3"
    ]
  }
}
</output_format>

Important: Ensure that all content in the output is in #LANG# language.

Analyze the provided meeting transcript carefully and generate the detailed and overall summaries as specified. 
    ** Make sure that the 'summary-time-details' section covers the entire meeting time from start to finish.
    ** Present your final output in the JSON format described above.
`,
	},
];

export const skCoustomPrompts = {
	user: [
		`<body>
            ##DATA##
            </body>`,
		`
            topics : ##TOPCIS##
            stt_results : ##DATA##
            `,
	],
	prompt: [
		`
For given STT results of the business meeting, the task is to extract key topics of business meeting.
Note that output sholud be in Korean.

Keep following points in mind when writing topics referring to STT results:
    1. Must Be Concise and Keep It Brief: Provide information clearly and succinctly.
    2. Must Be MECE: Ensure the topics are MECE(Mutually Exclusive Collectively Exhaustive), and can cover whole content of the meeting.
    3. Present the Main Topics Objectively: Avoid personal opinions or interpretations.
    4. Use Your Own Words: Paraphrase the original information authentically.    
    
For extracting key topics, follow the steps:
    Step 1. Divide STT results into semantically related segments.
    Step 2. Extract key topic from each segment.
    Step 3. Keep extracted topics if they are business-critical or being deeply dicussed during the meeting.

----
Input

stt_results: str, STT results of the business meeting in Korean and the format of followings:
    [
        {
            "speaker": "1",
            "time": "00:00:01",
            "content": "Speech content"
        },
        {
            "speaker": "2",
            "time": "00:02:42",
            "content": "Speech content"
        },
        ...
    ]

----
Output

Please return Extracted topics in following JSON format:
    {
        "meeting-topics" : [
            {TOPIC_1}, ..., {TOPIC_N}
        ]
    }
`,
		`
For given topics that discussed during the meeeting and full STT results of the meeting, the task is to generate meeting minutes.
Note that meeting minutes should contain all the important informations so that absentees can follow-up the contents of the meeting

Meeting minutes sholud contain title of the meeting minutes, keywords, and detailed informations like details, decisions, action items about topics.:
    1. (Required) title: Generate proper title for summarized meeting minutes. Note that a person should be able to guess the approximate content of the meeting just by looking at the title.
    2. (Required) keywords : Extract keywords of the summarized meeting minutes. Keep in mind that number of keywords never exceed 10.
    3. (Required) summary: Based on the whole stt_results, summarize the main points of the meeting in an explanatory style. Keep the summary concise and within 200 characters.
    4. (Required) details: Detailed explanations covering the topic. It should contain informations such as current status, issues and especially important numbers.
    5. (Optional) decisions: Critical choices that made during the meeting.
    6. (Optional) action-items: Task assigned to a person or group to be completed after the meeting. A person in charge must be assigned. If no specific person is mentioned, designate the speaker as the responsible person. Due date is optional. Dudate might be included if mentioned. If not mentioned just leave it 'TBD'.
In case of '4. details', '5. decisions', '6. action-items', Extract the key information without missing anything. Avoid outputting it as one long sentence. Include sufficient details and break the content into multiple sentences and ensure it is presented in bullet points.
And each sentence of '4. details', '5. decisions', '6. action-items' sholud include the time stamp of the relevant section. Do not write content using only the text associated with the included time stamp. Consider all relevant sections, but include the time stamp of the most relevant or starting text.

Keep following points in mind when writing meeting minutes:
    1. Must Be Concise and Detailed: Provide information clearly and in detail.
    2. Include Relevant Supporting Details: Add essential details that explains the main topic.
    3. Present the Main Ideas Objectively: Avoid personal opinions or interpretations.
    4. Use Your Own Words: Paraphrase the original information authentically.
    5. Must Be Coherent: Ensure the meeting minutes flows logically and is easy to follow.

To generate meeting minutes, follow below steps.
    Step 1. Throughly review STT results.
    Step 2. Write down meeting summary.
    Step 3. For each topic, extract details, decisions and action items.
    Step 4. Write down meeting minutes logically and fluently.
    Step 5. Generate proper title.
    Step 6. Extract Keywords.

----
Input

User will give topics and stt results in following format:
    topics: [TOPIC_1, TOPIC_2, ...]
    stt_results:
        [ {TIME_STAMP} ] speaker1: {TRANSCRIPTS}
        [ {TIME_STAMP} ] speaker2: {TRANSCRIPTS}
        ...

----
Output

Please returns meeting minutes in Korean, in the following JSON format:
    {
        "minutes":{
            "title": {TITLE_OF_MINUTES}, # Required. Title of the minutes that best represents the topics discussed at the meeting.
            "keywords": {KEYWORD_1}/.../{KEYWORD_N}, # Required. Provide maximum 10 keywords prioritized by importance, not in sequential order, but spanning the entire content.
            "summary": {SUMMARY}, # Required. Meeting Summary.
            "topics":[ #Required. Generate topic elements for all provided topics without missing any.
                {
                    "title": {TOPIC_1},
                    "details": [ # Required. Detailed information about topic.
                        {
                            "timestamp": {DETAIL_1_TIME_STAMP_ABOUT_TOPIC_1},
                            "content": {DETAIL_1_CONTENT_ABOUT_TOPIC_1}
                        },
                        {...},
                        ...
                    ],
                    "decisions": [  # Optional. Decisions made about topic, if it exists.
                        {
                            "timestamp": {DECISION_1_TIME_STAMP_ABOUT_TOPIC_1},
                            "content": {DECISION_1_CONTENT_ABOUT_TOPIC_1}
                        },
                        {...},
                        ...
                    ],
                    "action-items": [ # Optional. Action items about topic, if it exists.
                        {
                            "timestamp": {ACTION_ITEM_1_TIME_STAMP_ABOUT_TOPIC_1}, #Required
                            "content": {ACTION_ITEM_1_CONTENT_ABOUT_TOPIC_1}, #Required
                            "assignee": {ACTION_ITEM_1_ASSIGNEE_ABOUT_TOPIC_1}, #Required
                            "dueDate": {ACTION_ITEM_1_DUE_DATE_ABOUT_TOPIC_1}, #Required
                        },
                        {...},
                        ...
                    ]
                },
                {...},
                ...
            ]
        }
    }
`,
	],
};
