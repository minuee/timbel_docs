"""Full-guide structure: six parts, 23 units (19 real + 4 placeholders)."""

PLACEHOLDERS = {
 "P1_open-minutes": {
   "title": "회의록 열어보기",
   "todo": ["AI 요약 결과 화면 구성",
            "녹취록(음성 기록) 보기",
            "화자 구분 · 시간 이동"]},
 "P2_edit-share": {
   "title": "편집 · 공유 · 다운로드",
   "todo": ["회의록 내용 편집하기",
            "다른 사람에게 공유하기",
            "문서 파일로 내려받기"]},
 "P3_my-minutes": {
   "title": "미완성 회의록",
   "todo": ["미완성 회의록이 생기는 경우",
            "목록에서 확인하는 방법",
            "이어서 처리하는 방법"]},
 "P4_admin": {
   "title": "관리자 설정",
   "todo": ["사용자 관리",
            "조직 · 권한 설정",
            "기관 단위 이용 현황"]},
}

SECTIONS = [
 ("1부. 시작하기",        ["18_lnb-menus", "10_home-right"]),
 ("2부. 회의록 만들기",   ["06_record", "07_ai-template", "08_template-types"]),
 ("3부. 회의록 확인하기", ["P1_open-minutes", "P2_edit-share"]),
 ("4부. 회의록 정리하기", ["01_create-folder", "02_folder-menu", "03_rename-folder",
                           "04_delete-folder", "05_move-to-folder"]),
 ("5부. 회의록 찾기",     ["11_search", "12_calendar", "14_bookmark"]),
 ("6부. 관리와 설정",     ["13_inbox", "15_recycle",
                           "16a_usage-period", "16b_usage-metrics",
                           "17a_dictionary-open", "17b_dictionary-add",
                           "P3_my-minutes", "P4_admin"]),
]

ALL_UNITS = [u for _, us in SECTIONS for u in us]
REAL_UNITS = [u for u in ALL_UNITS if not u.startswith("P")]
NUMBER = {u: i for i, u in enumerate(ALL_UNITS, 1)}


def title_of(unit, UNITS):
    return PLACEHOLDERS[unit]["title"] if unit.startswith("P") else UNITS[unit]["title"]
