export default {
	system: `# [Instruction]
"X-bar theory"를 적용하여 "Target Segment"을 자연스러운 [[한국어]]로 번역합니다.
음차의 경우 번역을 진행하되, 예외적으로 문맥상 전문 용어, 응용은 그대로 유지합니다.

# [Strong Instruction]
>> 반드시 JSON 형식 그대로 유지합니다.
>> 출력은 어떠한 마크다운 서식이나 코드 블록 기호 없이 원시 JSON 형태로만 제공하세요.

# [Output Format]
{
  "isModified": true,
  "segments": [
    {
      "segmentId": "[segment ID]",
      "isTarget": true,
      "speakerId": [speaker ID number],
      "text": "[text content]"
    }
  ]
}
  
# [Example]
**Input example:**
[
  {
    "text": "회의를 진행하겠습니다.",
    "segmentId": "f674f05e-f2af-4b14-b2fd-08eadf35a81e",
    "speakerId": 1
  },
  {
    "text": "오늘 회의는 무엇인가요?",
    "segmentId": "f57c8ac3-9f04-4597-ac5d-11404446d4c2",
    "speakerId": 2
  },
  {
    "text": "I have a question for you. What kind of code can be encoded in this? As far as I know, it is MP4. Depending on the file, I understand that the voice change.",
    "isTarget": true,
    "segmentId": "52cdf82a-6885-48e3-b4d1-42a2570237d6",
    "speakerId": 1
  },
  {
    "text": "아이폰에서 녹음하는 것과 안드로이드에서 녹음하는 것이 다른가요?",
    "segmentId": "d60ed3d3-501f-4b80-a2b0-6686e294ee80",
    "speakerId": 2
  },
  {
    "text": "지금 움직이는 방식이 조금 달라 보입니다. 안드로이드에 업로드되는 파일들은 보통",
    "segmentId": "9fd5afaf-2d54-4a6c-adee-fd89a48d4040",
    "speakerId": 1
  }
]

**Output example :**
{
  "isModified": true,
  "segments": [
    {
      "segmentId": "52cdf82a-6885-48e3-b4d1-42a2570237d6",
      "isTarget": true,
      "speakerId": 1,
      "text": "질문 하나 드리고 싶습니다. 어떤 코드가 이 안에 인코딩될 수 있나요? 제가 아는 한, MP4와 알고 있습니다. 파일에 따라, 목소리가 변하는 것으로 알고 있습니다."
    }
  ]
}
`,
	user: `\n----
  주어진 데이터:
  ##DATA##
  `,
};
