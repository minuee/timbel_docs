-- =====================================================
-- ASST Service 어드바이저 스키마 DDL 스크립트
-- 생성일: 2025-01-XX
-- 설명: 어드바이저 서비스의 모든 테이블 생성 스크립트
-- =====================================================

-- 스키마 생성
CREATE SCHEMA IF NOT EXISTS advisor;

-- =====================================================
-- 1. 센터 테이블 (centers)
-- =====================================================
CREATE TABLE advisor.centers (
    id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) COMMENT '센터 정보';

-- =====================================================
-- 2. 팀 테이블 (teams)
-- =====================================================
CREATE TABLE advisor.teams (
    id VARCHAR(50) NOT NULL,
    center_id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (center_id) REFERENCES advisor.centers(id) ON DELETE CASCADE ON UPDATE CASCADE
) COMMENT '팀 정보';

-- =====================================================
-- 3. 사용자 테이블 (users)
-- =====================================================
CREATE TABLE advisor.users (
    id VARCHAR(50) NOT NULL,
    user_key VARCHAR(50) NOT NULL UNIQUE,
    team_id VARCHAR(50) NOT NULL,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    birth VARCHAR(10),
    gender INT(1),
    tel_num VARCHAR(64),
    ext_num VARCHAR(8),
    mobile VARCHAR(20),
    description TEXT,
    role VARCHAR(20),
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (team_id) REFERENCES advisor.teams(id) ON DELETE CASCADE ON UPDATE CASCADE
) COMMENT '사용자 정보';

-- =====================================================
-- 4. 대분류 테이블 (major_categories)
-- =====================================================
CREATE TABLE advisor.major_categories (
    id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    ord INT NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) COMMENT '대분류 카테고리';

-- =====================================================
-- 5. 중분류 테이블 (middle_categories)
-- =====================================================
CREATE TABLE advisor.middle_categories (
    id VARCHAR(50) NOT NULL,
    major_categories_id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    ord INT NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (major_categories_id) REFERENCES advisor.major_categories(id) ON DELETE CASCADE ON UPDATE CASCADE
) COMMENT '중분류 카테고리';

-- =====================================================
-- 6. 소분류 테이블 (minor_categories)
-- =====================================================
CREATE TABLE advisor.minor_categories (
    id VARCHAR(50) NOT NULL,
    middle_categories_id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    ord INT NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (middle_categories_id) REFERENCES advisor.middle_categories(id) ON DELETE CASCADE ON UPDATE CASCADE
) COMMENT '소분류 카테고리';

-- =====================================================
-- 7. 상담유형분류 테이블 (cs_classifications)
-- =====================================================
CREATE TABLE advisor.cs_classifications (
    id VARCHAR(50) NOT NULL,
    call_id VARCHAR(50) NOT NULL,
    user_key VARCHAR(50) NOT NULL,
    major_categories_id VARCHAR(50) NOT NULL,
    middle_categories_id VARCHAR(50) NOT NULL,
    minor_categories_id VARCHAR(50) NOT NULL,
    summary TEXT,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (major_categories_id) REFERENCES advisor.major_categories(id) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (middle_categories_id) REFERENCES advisor.middle_categories(id) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (minor_categories_id) REFERENCES advisor.minor_categories(id) ON DELETE CASCADE ON UPDATE CASCADE
) COMMENT '상담유형분류';

-- =====================================================
-- 8. 상담유형분류 키워드 테이블 (cs_classification_keywords)
-- =====================================================
CREATE TABLE advisor.cs_classification_keywords (
    id VARCHAR(50) NOT NULL,
    cs_classifications_id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (cs_classifications_id) REFERENCES advisor.cs_classifications(id) ON DELETE CASCADE ON UPDATE CASCADE
) COMMENT '상담유형분류 키워드';

-- =====================================================
-- 9. 코칭 요청 테이블 (coaching_requests)
-- =====================================================
CREATE TABLE advisor.coaching_requests (
    id VARCHAR(64) NOT NULL,
    call_id VARCHAR(64) NOT NULL,
    sender_key VARCHAR(64) NOT NULL,
    receiver_key VARCHAR(64) NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    is_important BOOLEAN NOT NULL DEFAULT FALSE,
    priority_type INT(1) NOT NULL DEFAULT 0 COMMENT '0: 일반, 1: 긴급',
    content TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) COMMENT '코칭 요청';

-- =====================================================
-- 10. 코칭 테이블 (coachings)
-- =====================================================
CREATE TABLE advisor.coachings (
    id VARCHAR(64) NOT NULL,
    call_id VARCHAR(64) NOT NULL,
    coaching_request_id VARCHAR(64),
    sender_key VARCHAR(64) NOT NULL,
    receiver_key VARCHAR(64) NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    is_important BOOLEAN NOT NULL DEFAULT FALSE,
    priority_type INT(1) NOT NULL DEFAULT 0 COMMENT '0: 일반, 1: 긴급',
    content TEXT,
    sender_name VARCHAR(100),
    customer_name VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (coaching_request_id) REFERENCES advisor.coaching_requests(id) ON DELETE SET NULL ON UPDATE CASCADE
) COMMENT '코칭';

-- =====================================================
-- 11. 통화 카테고리 테이블 (call_categories)
-- =====================================================
CREATE TABLE advisor.call_categories (
    callstats_id VARCHAR(64) NOT NULL,
    external_categories_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (callstats_id)
) COMMENT '통화 카테고리';

-- =====================================================
-- 12. 메모 그룹 테이블 (memo_groups)
-- =====================================================
CREATE TABLE advisor.memo_groups (
    id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    user_key VARCHAR(50) NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) COMMENT '메모 그룹';

-- =====================================================
-- 13. 메모 테이블 (memos)
-- =====================================================
CREATE TABLE advisor.memos (
    id VARCHAR(50) NOT NULL,
    memo_groups_id VARCHAR(50) NOT NULL,
    user_key VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (memo_groups_id) REFERENCES advisor.memo_groups(id) ON DELETE CASCADE ON UPDATE CASCADE
) COMMENT '메모';

-- =====================================================
-- 14. 공지사항 테이블 (notices)
-- =====================================================
CREATE TABLE advisor.notices (
    id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    is_urgent BOOLEAN NOT NULL DEFAULT FALSE,
    content TEXT NOT NULL,
    remind_time TIMESTAMP NULL,
    creator_key VARCHAR(100) NOT NULL,
    target_key VARCHAR(100) NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) COMMENT '공지사항';

-- =====================================================
-- 15. 공지사항 읽음 테이블 (notices_reads)
-- =====================================================
CREATE TABLE advisor.notices_reads (
    id VARCHAR(50) NOT NULL,
    notices_id VARCHAR(50) NOT NULL,
    user_key VARCHAR(100) NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (notices_id) REFERENCES advisor.notices(id) ON DELETE CASCADE ON UPDATE CASCADE
) COMMENT '공지사항 읽음 정보';

-- =====================================================
-- 16. 즐겨찾기 테이블 (favorites)
-- =====================================================
CREATE TABLE advisor.favorites (
    id VARCHAR(50) NOT NULL,
    user_key VARCHAR(50) NOT NULL,
    type_alias VARCHAR(20) NOT NULL COMMENT 'users, calls, coachings, memos 등',
    target_id VARCHAR(20) NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) COMMENT '즐겨찾기';

-- =====================================================
-- 17. 키워드 감지 테이블 (keyword_detects)
-- =====================================================
CREATE TABLE advisor.keyword_detects (
    id VARCHAR(50) NOT NULL,
    keyword VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,
    creator_key VARCHAR(50) NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) COMMENT '키워드 감지';

-- =====================================================
-- 18. 환경설정 테이블 (configs)
-- =====================================================
CREATE TABLE advisor.configs (
    id VARCHAR(50) NOT NULL,
    user_key VARCHAR(50) NOT NULL,
    alias VARCHAR(255) NOT NULL,
    value VARCHAR(255) NOT NULL,
    create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) COMMENT '환경설정';

-- =====================================================
-- 인덱스 생성
-- =====================================================

-- 사용자 테이블 인덱스
CREATE INDEX idx_users_user_key ON advisor.users(user_key);
CREATE INDEX idx_users_team_id ON advisor.users(team_id);
CREATE INDEX idx_users_email ON advisor.users(email);

-- 팀 테이블 인덱스
CREATE INDEX idx_teams_center_id ON advisor.teams(center_id);

-- 카테고리 테이블 인덱스
CREATE INDEX idx_middle_categories_major_id ON advisor.middle_categories(major_categories_id);
CREATE INDEX idx_minor_categories_middle_id ON advisor.minor_categories(middle_categories_id);

-- 상담유형분류 테이블 인덱스
CREATE INDEX idx_cs_classifications_call_id ON advisor.cs_classifications(call_id);
CREATE INDEX idx_cs_classifications_user_key ON advisor.cs_classifications(user_key);
CREATE INDEX idx_cs_classifications_categories ON advisor.cs_classifications(major_categories_id, middle_categories_id, minor_categories_id);

-- 상담유형분류 키워드 테이블 인덱스
CREATE INDEX idx_cs_classification_keywords_cs_id ON advisor.cs_classification_keywords(cs_classifications_id);

-- 코칭 요청 테이블 인덱스
CREATE INDEX idx_coaching_requests_call_id ON advisor.coaching_requests(call_id);
CREATE INDEX idx_coaching_requests_sender_key ON advisor.coaching_requests(sender_key);
CREATE INDEX idx_coaching_requests_receiver_key ON advisor.coaching_requests(receiver_key);
CREATE INDEX idx_coaching_requests_is_read ON advisor.coaching_requests(is_read);
CREATE INDEX idx_coaching_requests_is_important ON advisor.coaching_requests(is_important);

-- 코칭 테이블 인덱스
CREATE INDEX idx_coachings_call_id ON advisor.coachings(call_id);
CREATE INDEX idx_coachings_sender_key ON advisor.coachings(sender_key);
CREATE INDEX idx_coachings_receiver_key ON advisor.coachings(receiver_key);
CREATE INDEX idx_coachings_coaching_request_id ON advisor.coachings(coaching_request_id);
CREATE INDEX idx_coachings_is_read ON advisor.coachings(is_read);
CREATE INDEX idx_coachings_is_important ON advisor.coachings(is_important);

-- 통화 카테고리 테이블 인덱스
CREATE INDEX idx_call_categories_external_categories_id ON advisor.call_categories(external_categories_id);

-- 메모 테이블 인덱스
CREATE INDEX idx_memos_user_key ON advisor.memos(user_key);
CREATE INDEX idx_memos_group_id ON advisor.memos(memo_groups_id);

-- 메모 그룹 테이블 인덱스
CREATE INDEX idx_memo_groups_user_key ON advisor.memo_groups(user_key);

-- 공지사항 테이블 인덱스
CREATE INDEX idx_notices_creator_key ON advisor.notices(creator_key);
CREATE INDEX idx_notices_target_key ON advisor.notices(target_key);
CREATE INDEX idx_notices_urgent ON advisor.notices(is_urgent);

-- 공지사항 읽음 테이블 인덱스
CREATE INDEX idx_notices_reads_notice_id ON advisor.notices_reads(notices_id);
CREATE INDEX idx_notices_reads_user_key ON advisor.notices_reads(user_key);

-- 즐겨찾기 테이블 인덱스
CREATE INDEX idx_favorites_user_key ON advisor.favorites(user_key);
CREATE INDEX idx_favorites_type_target ON advisor.favorites(type_alias, target_id);

-- 키워드 감지 테이블 인덱스
CREATE INDEX idx_keyword_detects_type ON advisor.keyword_detects(type);
CREATE INDEX idx_keyword_detects_creator ON advisor.keyword_detects(creator_key);

-- 환경설정 테이블 인덱스
CREATE INDEX idx_configs_user_key ON advisor.configs(user_key);
CREATE INDEX idx_configs_alias ON advisor.configs(alias);

-- =====================================================
-- 뷰 생성 (선택사항)
-- =====================================================

-- 사용자 상세 정보 뷰
CREATE VIEW advisor.user_details AS
SELECT 
    u.id,
    u.user_key,
    u.email,
    u.name,
    u.birth,
    u.gender,
    u.tel_num,
    u.ext_num,
    u.mobile,
    u.description,
    u.role,
    t.name as team_name,
    c.name as center_name,
    u.create_at,
    u.update_at
FROM advisor.users u
JOIN advisor.teams t ON u.team_id = t.id
JOIN advisor.centers c ON t.center_id = c.id;

-- 카테고리 계층 구조 뷰
CREATE VIEW advisor.category_hierarchy AS
SELECT 
    mc.id as major_id,
    mc.name as major_name,
    mc.ord as major_ord,
    midc.id as middle_id,
    midc.name as middle_name,
    midc.ord as middle_ord,
    minc.id as minor_id,
    minc.name as minor_name,
    minc.ord as minor_ord
FROM advisor.major_categories mc
LEFT JOIN advisor.middle_categories midc ON mc.id = midc.major_categories_id
LEFT JOIN advisor.minor_categories minc ON midc.id = minc.middle_categories_id
ORDER BY mc.ord, midc.ord, minc.ord;

-- =====================================================
-- 스크립트 완료
-- =====================================================

