# NeMo turn merge 로그 원본 — 2026-05-11 (한국은행 mock 세션)

> 본 파일은 client browser console 에서 캡처한 `nlp:complete` 이벤트 로그 원본입니다.
> 분석본은 `nemo-turn-eou-mismatch-server-request.md` 참조.
> 이전 캡처본(크레온/대신증권): `nemo-turn-eou-mismatch-logs-20260511.md`
>
> 채널: `dev:4609686:56356659:call:nlp:complete`
> agent: `56356659`
> 도메인: 한국은행 고객센터 mock (5콜 연속)
> 캡처 시점: 2026-05-11 client 측 §7 우회 적용 후
>
> 범례:
> - ⚠️ 이상치: `incomplete`/`transformative`/`connective` + `eou ≥ 0.8` (원안에선 누락, §7 우회 적용 후 병합됨)
> - ✅ 정상 미완: `incomplete`/`transformative`/`connective` + `eou < 0.8`
> - 🔄 turn 순서 역전 (서버 emit / 수신 순서 어긋남)
> - 🔁 짧은 interjection 분리 후보 (≤2자, 1자 interjection 위주)

---

## Call 1 — 인터넷뱅킹 로그인 오류 (turn 1–49)

```
turn=1  ending=interjection  eou=1     "아 아"
turn=2  ending=final         eou=0.95  "들리시나요"
turn=3  ending=final         eou=0.95  "네 네 들려요"
turn=4  ending=interjection  eou=1     "네 네"
turn=5  ending=incomplete    eou=0.5   "로그"                                                              ✅ 정상 미완
turn=6  ending=interjection  eou=1     "그"                                                                🔁 1자 interjection
turn=7  ending=incomplete    eou=0.5   "인터넷뱅킹 로 로그인 오류"                                          ✅ 정상 미완
turn=8  ending=interjection  eou=1     "네"                                                                🔁
turn=9  ending=final         eou=0.95  "이거부터 먼저 진행하겠습니다"
turn=10 ending=interjection  eou=1     "네"                                                                🔁
turn=11 ending=final         eou=0.95  "어 안녕하세요 한국은행 고객센터 상담사 김현모입니다 무엇을 도와드릴까요"
turn=12 ending=interjection  eou=1     "아 네 저"
turn=13 ending=final         eou=0.95  "지금 인터넷뱅킹이 안돼서요 계속 오류가 떠서요"
turn=14 ending=final         eou=0.95  "불편드려서 정말 죄송합니다 고객님 확인을 위해 통화 생년월일 말씀해 주시겠어요"
turn=15 ending=incomplete    eou=0.5   "아 김민준이고 1985년 3월 12일이요"                                  ✅ 정상 미완
turn=16 ending=incomplete    eou=0.95  "감사합니다 김"                                                     ⚠️ 이상치
turn=17 ending=final         eou=0.95  "고객님 지금 어떤 오류 메시지가 표시되고 있는지 말씀해 주실 수 있을까요"
turn=18 ending=final         eou=0.95  "알겠습니다"
turn=19 ending=interjection  eou=1     "어"                                                                🔁
turn=20 ending=connective    eou=0.5   "인증서가 만료되었습니다라고 뜨는데요 저 인증서 갱신한 지 얼마 안 되는데"  ✅ 정상 미완
turn=21 ending=incomplete    eou=1     "여기에는 보양 뭐 안에"                                             ⚠️ 이상치
turn=22 ending=final         eou=0.95  "혹시 김치나 생계 언제쯤 되셨나요"
turn=23 ending=final         eou=0.95  "한 2주 전인가 그때 분명히 했어요"
turn=24 ending=final         eou=0.95  "네 확인해 보겠습니다"
turn=25 ending=final         eou=0.95  "기다려 주시겠어요"
turn=26 ending=incomplete    eou=0.95  "고객님이 확인해 보니 갱신은 정상적으로 완료가 되셨는데요 혹시"        ⚠️ 이상치
turn=27 ending=final         eou=0.95  "지금 사용하시는 브라우저가 어디세요"
turn=28 ending=final         eou=0.95  "크롬 쓰고 있어요"
turn=29 ending=final         eou=0.95  "혹시 인터넷 익스 리스플로러나 엣지로 한번 시도해 보셨나요"
turn=30 ending=final         eou=0.95  "인터넷 뱅킹이 크롬에서 간월적으로 인증서 오류가 발생하는 이슈가 최근에 보그랩을 줬어요"
turn=31 ending=final         eou=0.95  "아 그래요"
turn=32 ending=final         eou=0.95  "미리 공지를 해줘야 되는 거 아니에요"
turn=33 ending=final         eou=0.95  "저 이것 때문에 오전에는 시간은 말랐어요"
turn=34 ending=incomplete    eou=0.95  "정말 죄송합니다 고객님"                                            ⚠️ 이상치
turn=35 ending=incomplete    eou=0.95  "말씀하신 게 맞습니다 안내가"                                       ⚠️ 이상치
turn=36 ending=incomplete    eou=0.95  "좀 더 빠르게 이루어졌어야 했는데 제가 고객님 불편 사항을 대구 시스템에 기록해 두겠습니다 현재"  ⚠️ 이상치
turn=37 ending=final         eou=0.95  "기자팀에서 패키지 작품이고 문시 방편으로 엣지 브라우저의 또는 정상 이용 가능하세요"
turn=38 ending=connective    eou=0.95  "엣지는 잘 안 써서 일단 뭐 해볼게요 근데"                            ⚠️ 이상치
turn=39 ending=final         eou=0.95  "네 언제 크롬에서도 되나요"
turn=40 ending=final         eou=0.95  "이번 주 내로 업데이트가 완료될 예정이라고 안내받았습니다"
turn=41 ending=final         eou=0.95  "불편하시더라도 그때까지만 엣지를 이용해 주시면 감사하겠습니다"
turn=42 ending=final         eou=0.95  "혹시 또 문제가 생기시면 바로 저희 쪽으로 연락 주십시오"
turn=43 ending=final         eou=0.95  "알겠어요 근데 이 진짜 이런 거 좀 미리미리 알려주세요"
turn=44 ending=final         eou=0.95  "제 이미지라는 게 없을 줄 알았던 정말 죄송합니다"
turn=45 ending=final         eou=0.95  "이번엔 젓가락 금지로 우편 취소할 수 있도록 하겠습니다"
turn=46 ending=final         eou=0.95  "다른 도움이 필요하신 건 없으신가요"
turn=47 ending=final         eou=0.95  "아니 일단 해볼게요"
turn=48 ending=incomplete    eou=0.95  "네 감사합니다 이용"                                                ⚠️ 이상치
turn=49 ending=final         eou=0.95  "감사하고 좋은 하루 보내세요"
```

---

## Call 2 — 주택담보대출 상담 (turn 50–99)

```
turn=50 ending=final         eou=0.95  "안녕하세요 한국은행 고객센터 김현모입니다 뭐 그 도와드릴까요"
turn=51 ending=interjection  eou=1     "네 저"
turn=53 ending=incomplete    eou=0.95  "주택담보대출 알아보고 있는데요 지금"                                ⚠️ 이상치 🔄 turn 53 → 52 순서 역전
turn=54 ending=final         eou=0.95  "금리가 어떻게 되나요"
turn=52 ending=incomplete    eou=0.95  "일단 4시 회의에 우리가 논의를 좀 이해할 수 있도록 받으려고 합니다 그거는"  ⚠️ 이상치 🔄 (53,54 뒤 도착)
turn=55 ending=incomplete    eou=0.95  "그 용기를 보는데 고객님 현재 주택담보대출 경우는 변동금리 기준으로 위한 4.5%에서 5.8% 사이고요 그 카드 요금 금리는 연 42%에서 52% 수준입니다 고객님"  ⚠️ 이상치
turn=56 ending=final         eou=0.95  "신경들과 액티브이 비율에 따라 달라질 수 있습니다"
turn=57 ending=final         eou=0.95  "LTE가 뭐예요"
turn=58 ending=incomplete    eou=0.95  "아 거기에 보면 이제 아 죄송합니다 뭐 예 설명을 드릴게요 액티브"      ⚠️ 이상치
turn=59 ending=final         eou=0.95  "우리 담보 인정 비율이라고 해서요"
turn=60 ending=incomplete    eou=0.95  "말씀드리면 집값 대비 얼마까지 출금은 가능한지를 말씀드리는 거예요 예를"  ⚠️ 이상치
turn=62 ending=incomplete    eou=0.95  "아 그래요 저는"                                                    ⚠️ 이상치 🔄 turn 62→63→61 순서 역전
turn=63 ending=final         eou=0.95  "지금 45000원짜리 아파트 살 건데요 2억 5000 정도 대출받고 싶거든요"
turn=61 ending=final         eou=0.95  "5자리 칩을 전부 다 보면은 기분이 70%면 최대 3억 5000만 원 거의 대출이 가능하다던 것이 발생할 기원 취하율을 알려주세요"  🔄 (62,63 뒤 도착)
turn=64 ending=connective    eou=0.95  "네 네 그러면은 LTE가 약 55.5% 정도 되는데요 그래서"                ⚠️ 이상치
turn=65 ending=incomplete    eou=0.95  "대상 지역 여부에 따라 엘티 브이 한도가 달라질 수 있어요 혹시"       ⚠️ 이상치
turn=66 ending=final         eou=0.95  "이 해당 아파트가 어느 지역인지 여쭤봐도 될까요"
turn=67 ending=final         eou=0.95  "경기도 수원인데요"
turn=68 ending=final         eou=0.95  "또 하나는 저장 대상 지역에서 해체된 지역이 있어서 세부 직후에 따라 달라질 수 있어요"
turn=69 ending=incomplete    eou=0.95  "담보 감정평가 후 확인이 가능한데요 현재"                            ⚠️ 이상치
turn=70 ending=incomplete    eou=0.95  "입장은 어떻게 되시나요 이 자식"                                    ⚠️ 이상치
turn=71 ending=final         eou=0.95  "여부도 국내 영향을 미칩니다"
turn=72 ending=interjection  eou=1     "네"                                                                🔁
turn=73 ending=final         eou=0.95  "직장인이에요 중경기업 다니는데 연봉은 한 오천 오백 정도 되는 거 같아요"
turn=75 ending=incomplete    eou=1     "네 그랬"                                                           ⚠️ 이상치 🔄 turn 75→74 순서 역전
turn=74 ending=final         eou=0.95  "첫 번째 접종을 하시는 네 그 정도는 상당히 우대금리 적용이 가능한 것 같습니다 고객님 신용 점수로 혹시 알고 계신가요"  🔄
turn=76 ending=final         eou=0.95  "마지막에 봤을 때 850점이었는데 그게 좀 오래됐어요"
turn=77 ending=final         eou=0.95  "450점이면 모든 것이 전이라 우대금리 최대 적용이 가능하세요"
turn=78 ending=final         eou=0.95  "변동금리 기준으로 가스 인포작될 것 같게 나올 가능성은 높습니다"
turn=79 ending=final         eou=0.95  "다만 정확한 금리는 실제 심사를 거쳐야 나오고요"
turn=80 ending=final         eou=0.95  "변동이랑 고장이랑 어떤 게 더 나을까요 요즘 금리 오른다고 하잖아요"
turn=81 ending=incomplete    eou=0.95  "제가 어느 게 낫다고 변경 지역 말씀드리기는 어렵고요 다만 일반적으로 금리 상승 시에는 보증금리가 안정적이에요 대"  ⚠️ 이상치
turn=82 ending=final         eou=0.95  "초기에는 조금 더 높은 편이에요 반대로 장성 금리는 금리가 내려가면 이득이지만 그러면 이자 부담이 커지면 있습니다"
turn=84 ending=final         eou=0.95  "네 10시요 감사합니다"                                              🔄 turn 84→83 순서 역전
turn=83 ending=final         eou=0.95  "고객님 상황 계획이나 리스크 허용 범위에 따라 달라질 것 같습니다"   🔄
turn=85 ending=final         eou=1     "그럼 괜찮아"
turn=86 ending=incomplete    eou=1     "네 저는 그 시간부터 확인할려고 하는데 그 몇 분 넘"                  ⚠️ 이상치
turn=87 ending=interjection  eou=1     "아"                                                                🔁
turn=88 ending=final         eou=0.95  "아니 아니 없습니다"
turn=89 ending=interjection  eou=1     "아 음"
turn=90 ending=final         eou=0.95  "일단 고정으로 가는 게 마음이 편할 것 같긴 한데 1번 더 생각해볼게요 신청은 어떻게 해요"
turn=91 ending=final         eou=0.95  "여기 가서 제가 한번 쭉 보고 드릴게요 이걸 봐주시면 될 것 같습니다"
turn=92 ending=incomplete    eou=0.95  "아직 본격 같은 거 다 잠시만"                                       ⚠️ 이상치
turn=93 ending=interjection  eou=1     "네"                                                                🔁
turn=94 ending=final         eou=0.95  "어 통화 종료나 이렇게 일단 잘 못 잡는 알겠습니다"
turn=95 ending=final         eou=0.95  "인터넷 검침이나 웹에서 다른 심사 신청이 가능하시고요 가까운 영업점 방문하셔도 됩니다"
turn=96 ending=final         eou=0.95  "다른 심사 결과가 나오면 정확한 준비랑 함께 확인할 수 있어요"
turn=97 ending=final         eou=0.95  "영업점 예약 후 도와드릴 수 있습니다"
turn=98 ending=final         eou=0.95  "아 그래요 그럼 수원 영업점 예약 부탁드릴게요"
turn=99 ending=final         eou=0.95  "응답입니다 수원 지역 영업점으로 연결해 드릴게요 잠시만 기다려 주시겠어요"
```

---

## Call 3 — 카드 부정 사용 (turn 100–135)

```
turn=100 ending=final         eou=0.95 "다음 거 하겠습니다"
turn=101 ending=final         eou=0.95 "안녕하세요 한국은행 고객센터입니다 무엇을 도와드릴까요"
turn=102 ending=final         eou=0.95 "아 저 지금 카드 문자가 왔는데요 제가 쓴 게 아닌 거 같은데 빨리 좀 해주세요"
turn=103 ending=final         eou=0.95 "네 고객님 걱정하지 마세요 제가 바로 도와드리겠습니다 빠른 확인을 위해 성함과 카드 검색 네 자리 말씀해 주시겠어요"
turn=104 ending=incomplete    eou=0.5  "박서연이고요 카드 뒷번호는 78232"                                  ✅ 정상 미완
turn=105 ending=final         eou=0.95 "네 박서영 고객님 어떤 내용의 문자를 받으셨나요"
turn=106 ending=final         eou=0.95 "방금 120만 원 결제됐다는 문자요 저 지금 집에 있는데 카드도 여기 다 있거든요"
turn=107 ending=final         eou=0.95 "초록 수업 역시 네 즉시 확인해 드리겠습니다"
turn=108 ending=incomplete    eou=0.95 "저는 먼저 해당 카드 일시정지 처리해드릴까요 이 추가"                ⚠️ 이상치
turn=109 ending=final         eou=0.95 "피해를 막을 수 있습니다"
turn=110 ending=final         eou=0.95 "네 일단 마가주세요"
turn=111 ending=interjection  eou=1    "어"                                                                🔁
turn=112 ending=interjection  eou=1    "그"                                                                🔁
turn=113 ending=final         eou=0.95 "특히 경제 처리 완료했습니다"
turn=114 ending=incomplete    eou=0.95 "근데 오매우고 2시에 17분에 온라인 쇼핑몰에서 119만 8000원 결제가 있었고요 고객"  ⚠️ 이상치
turn=115 ending=final         eou=0.95 "결제하신 게 맞는지 확인이 어려우신 거죠"
turn=116 ending=incomplete    eou=1    "네 저 절"                                                          ⚠️ 이상치
turn=117 ending=final         eou=0.95 "안 떴어요 이게 어떻게 된 거예요"
turn=118 ending=final         eou=0.95 "고객님 우선 정식 부정 사용은 이의신청을 접수해 드리겠습니다"
turn=119 ending=final         eou=0.95 "이의신청이 완료되면 카드사 조사를 통해 부정 사용으로 확인될 경우 전액 환급 환급받으실 수 있습니다"
turn=120 ending=final         eou=0.95 "조사하는데 얼마나 걸려요"
turn=121 ending=final         eou=0.95 "통상적으로 영업일 기준을 10일에서 14일 정도 소요됩니다"
turn=122 ending=final         eou=0.95 "조사 결과에 따라 추가 서류가 필요한 수 있고요"
turn=123 ending=final         eou=0.95 "그럼 그 120만 원은 일단 제가 내야 하는 건가요"
turn=124 ending=final         eou=1    "근데 개발사와 추천인 거죠"
turn=125 ending=final         eou=0.95 "1순정 접수가 완료되면 해당 결제 건은 보류 처리가 되어 고객님 청구서에 포함되지 않습니다"
turn=126 ending=final         eou=0.95 "조사 기간 중에는 납부 의무가 발생하지 않으세요"
turn=127 ending=final         eou=0.95 "아 다행이네요 그리고 혹시 제 카드 정보가 어디서 유출된 건지 알 수 있나요"
turn=128 ending=final         eou=0.95 "대부분 정확한 이제 최 경로는 저희가 직접 확인하기 어렵지만은 최근에 피싱 사이트나 그 분명한 사이트에서 카드 결제를 하신 적 있으신가요"
turn=129 ending=interjection  eou=1    "어"                                                                🔁
turn=130 ending=final         eou=0.95 "지난주에 처음 보는 쇼핑몰에서 샀는데 그게 문제일 수도 있겠네요"
turn=131 ending=final         eou=0.95 "그럴 가능성이 있습니다 앞으로는 고민된 쇼핑몰 위주로 이용하시고 모르는 사이트에서는 가상 카드 번호를 수신 걸 권장드립니다"
turn=132 ending=final         eou=0.95 "저희 앱에서 1회용 가상 카드 번호 발급이 가능하세요"
turn=133 ending=final         eou=0.95 "아 그럼 그 기능이 있었네요 알겠어요 이의신청은 어떻게 진행되나요"
turn=134 ending=incomplete    eou=0.95 "제가 지금 다른 접수해 드리겠습니다 접수"                            ⚠️ 이상치
turn=135 ending=final         eou=0.95 "완료되면 문자로 신청번호 발송해드리고 진행사항은 웹에서도 확인 가능하세요"
```

---

## Call 4 — 적금 만기 (turn 136–186)

```
turn=137 ending=interjection  eou=1    "네"                                                                🔄 turn 137→136 순서 역전 / 🔁
turn=136 ending=final         eou=0.95 "방법을 안녕하세요 한국은행 고객센터입니다"                          🔄
turn=138 ending=final         eou=0.95 "무엇을 도와드릴까요"
turn=139 ending=final         eou=0.95 "저 적금 만기가 다음 달인데요 해지"
turn=140 ending=final         eou=0.95 "다시 넣을 건데 어떻게 하면 되나요"
turn=141 ending=final         eou=0.95 "네 고객님 성함과 생년월일 확인 먼저 부탁드리겠습니다"
turn=142 ending=final         eou=0.95 "최지원이고요"
turn=143 ending=incomplete    eou=0.5  "590년 7월 5일이요"                                                 ✅ 정상 미완
turn=144 ending=incomplete    eou=1    "그 소"                                                             ⚠️ 이상치
turn=145 ending=final         eou=0.95 "감사합니다"
turn=146 ending=final         eou=0.95 "고객님 현재 가입하신 적금 상품명이나 계좌번호 알고 계신가요"
turn=147 ending=interjection  eou=1    "아"                                                                🔁
turn=148 ending=final         eou=0.95 "행복 적금이요 계좌 번호는 지금 수첩이 있는데 모르겠어요 앱에서 보면 되나요"
turn=149 ending=final         eou=0.95 "네 왜 로그인 후 내 계좌 탭에서 확인하실 수 있어요"
turn=150 ending=final         eou=0.95 "괜찮으시면 제가 고객님 가입 내역 조회해 드릴게요"
turn=151 ending=final         eou=0.95 "네 그렇게 해주세요"
turn=152 ending=final         eou=0.95 "잠시만요"
turn=153 ending=final         eou=0.95 "확인해보니 행복적근 2년 만기 상품에 가입되어 있으시고 만기일은 다음 달 15일이네요 5월 500000원씩 납입하셨고 만기 수령 예정액은 최저 기준 1210만 원입니다"
turn=154 ending=final         eou=0.95 "어 생각보다 이자가 많네요 세금은 얼마나 되나요"
turn=155 ending=incomplete    eou=0.95 "이자 소득세 15.4%가 적용되어 이자가"                               ⚠️ 이상치
turn=156 ending=final         eou=0.95 "약 10만 원 정도니까 매우 실수령액은 약 11009만 2000원 정도 되실 것 같아요"
turn=157 ending=final         eou=0.95 "아 그렇군요"
turn=158 ending=final         eou=0.95 "그럼 다시 적금 넣으려면 지금 어떤 상품이 좋을까요"
turn=159 ending=final         eou=0.95 "현대 판매 중인 상품 중에서는 플러스 정기적금은 인기가 많은데요"
turn=160 ending=incomplete    eou=0.95 "인자 만두 비전이면 4% 있고요 자동"                                 ⚠️ 이상치
turn=161 ending=final         eou=0.95 "재설정 시 0.2퍼센트 우대 금리 추가로 받으실 수 있고요"
turn=162 ending=final         eou=0.95 "예전에 들었던 행복 적금이 3.5%였는데 지금이 더 높네요"
turn=163 ending=final         eou=0.95 "네 맞습니다"
turn=164 ending=final         eou=0.95 "최근 기준금리 조정으로 접근 금리도 쏙콕 올랐어요 2년짜리도 있는데 그건 4.3% 3%입니까"
turn=165 ending=final         eou=0.95 "2년짜리 금리가 더 높네요 근데 2년 동안 돈이 묶이는 거잖아요"
turn=166 ending=incomplete    eou=0.95 "맞습니다 중도"                                                     ⚠️ 이상치
turn=167 ending=final         eou=0.95 "약정 금리 대신 중도해지 금리가 제공되어 이자가 많이 줄어드니까요"
turn=168 ending=final         eou=0.95 "계획에 맞게 선택하시는 게 좋을 것 같아요"
turn=169 ending=final         eou=0.95 "음 그럼 1년짜리로 할게요 만기 되면 자동으로 재가입로 되나요"
turn=170 ending=final         eou=0.95 "네 가입 시 만기 자동 제 예치 옵션 선택하시면 만기 후 자동 이체 가입됩니다"
turn=171 ending=final         eou=0.95 "아마 제가 직접 금리가 좋은 점이죠 참고해 주세요"
turn=172 ending=final         eou=0.95 "알겠어요 만기 되고 나서 바로 신청할게요"
turn=173 ending=incomplete    eou=0.95 "네 만기 당일 웹이나 영업점에서 처리 가능하세요 혹시"                ⚠️ 이상치
turn=174 ending=transformative eou=0.95 "암기하기 전 서비스 신청을 했나요 안될"                            ⚠️ 이상치
turn=175 ending=final         eou=0.95 "제가 등록해 드릴게요"
turn=176 ending=final         eou=0.95 "아 그거 신청해 주세요"
turn=177 ending=final         eou=0.95 "근데 지금 바로 등록 완료했습니다"
turn=178 ending=incomplete    eou=0.95 "3일 전에 문자 발송될 예정입니다 도움이"                            ⚠️ 이상치
turn=179 ending=final         eou=0.95 "음 없어요 감사합니다"
turn=180 ending=final         eou=0.95 "감사합니다 고객님 좋은 하루 보내세요"
turn=181 ending=final         eou=0.95 "잠시만요"
turn=182 ending=interjection  eou=1    "네"                                                                🔁
turn=183 ending=incomplete    eou=0.95 "3일 전에 문서 발송될 예정입니다 더 도움이"                         ⚠️ 이상치
turn=184 ending=final         eou=0.95 "필요하신 건 없으신가요"
turn=185 ending=incomplete    eou=0.5  "필요하신 거"                                                       ✅ 정상 미완
turn=186 ending=incomplete    eou=0.5  "다음 거"                                                           ✅ 정상 미완
```

---

## Call 5 — 대출 연체 (turn 187–215+, 일부 truncated)

```
turn=187 ending=final         eou=0.95 "안녕하세요 한국은행 고객센터입니다 무엇을 도와드릴까요"
turn=188 ending=final         eou=0.95 "저 지금 대출 연체됐다고 문자가 왔는데요 어떻게 해야 하나요"
turn=189 ending=final         eou=0.95 "네 고객님이 먼저 제가 도와드리겠습니다 먼저 확인을 위해 성함과 생년월일 말씀해 주시겠어요"
turn=190 ending=incomplete    eou=0.5  "이준혁이고 1988년 11월 21일"                                       ✅ 정상 미완
turn=191 ending=final         eou=0.95 "이준혁 고객님 확인해 드리겠습니다"
turn=192 ending=final         eou=0.95 "잠시만요"
turn=193 ending=incomplete    eou=0.95 "현재 개인 신용대출 10000000원 상품이 5일 연체 중이시네요 이런 상황이"  ⚠️ 이상치
turn=194 ending=final         eou=0.95 "힘드신가요"
turn=195 ending=incomplete    eou=0.5  "네 사실 얼마 전에"                                                 ✅ 정상 미완
turn=197 ending=incomplete    eou=0.5  "그 자리보다"                                                       ✅ 정상 미완 🔄 turn 197→196 순서 역전
turn=196 ending=final         eou=0.95 "권고 해지당해서요 그래서 이번 달 납부를 못했네요"                  🔄
turn=198 ending=final         eou=0.95 "많이 언니 흔드셨겠어요"
turn=199 ending=final         eou=0.95 "일찍 하셔도 정말 걱정이 크실 것 같습니다"
turn=200 ending=final         eou=0.95 "도울 수 있는 방법을 쳐다보겠습니다 혹시 현재 제 지역 준비 중이신 건가요"
turn=201 ending=final         eou=1    "네 이력서 넣고 있긴 한데 뭐 언제 될지는 모르겠어요"
turn=202 ending=final         eou=0.95 "네 알겠습니다"
turn=203 ending=final         eou=0.95 "부모님 같은 경우에는 상환 유예 제도를 신청하실 수 있어요"
turn=204 ending=final         eou=0.95 "실직자의 경우 최저 6개월까지 원금 상환을 위해 될 수 있고요"
turn=205 ending=final         eou=0.95 "문자만 납부하시면 됩니다"
turn=206 ending=incomplete    eou=0.5  "이자만요 이자는 얼만데요"                                          ✅ 정상 미완
turn=207 ending=final         eou=0.95 "현재 대출 잔액이 980만 원 정도이시고요 금리 2.5% 기준으로 월 이자는 약 5만 3000원 수준입니다"
turn=208 ending=incomplete    eou=0.5  "그 정도라면 어떻게 해볼 수 있을 거 같아요 그거 신청하면 연체 기록은요"  ✅ 정상 미완
turn=209 ending=final         eou=0.95 "현재 5일 연체 상태가 이미 등록되어 있어요"
turn=210 ending=final         eou=0.95 "난 오늘 이자만이라고 납부하시고 위해 신청을 하시면 추가 연체는 막을 수 있어서 신용정보 하락을 최소할 수 있습니다"
turn=211 ending=interjection  eou=1    "아"                                                                🔁
turn=212 ending=final         eou=0.95 "제가 이렇게 될 줄 몰랐는데 대출받을 때는 멀쩡했었거든요"
turn=213 ending=final         eou=0.95 "충분히 이해합니다 고객님 갑작스러운 상황이 생기면 누구든 힘들 수 있어요"
turn=214 ending=final         eou=0.95 "지금 사람들 잘 정리하는 게 중요하니까 차근차근 같이 해봐요"
turn=215 ending=final         eou=0.95 "감사합니다 근데 유예 신청은 어떻게 해요"
... (이후 로그 잘림)
```