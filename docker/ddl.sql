-- ユーザーテーブル
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE, -- ユーザー名
    password VARCHAR(255) NOT NULL,        -- パスワード（ハッシュ化）
    email VARCHAR(255),                    -- メールアドレス
    goal TEXT,                             -- 学習目標
    weekly_target INTEGER,                 -- 週あたりの学習目標回数
    small_action TEXT,                     -- 小さな行動
    anchor TEXT,                           -- アンカー
    failure_days INTEGER                   -- 失敗の定義（日数）
);

-- 学習カテゴリ（学習内容）テーブル（ユーザーごとにカテゴリを管理）
CREATE TABLE IF NOT EXISTS study_categories (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_name TEXT NOT NULL
);

-- 関数を使ったユニーク制約はインデックスで作成する
CREATE UNIQUE INDEX IF NOT EXISTS unique_user_category_lower
ON study_categories (user_id, LOWER(category_name));


-- 学習記録テーブル
CREATE TABLE IF NOT EXISTS record (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    study_date DATE NOT NULL,
    study_time INTEGER NOT NULL,
    category_id INTEGER REFERENCES study_categories(id) ON DELETE SET NULL, -- ← 正しい外部参照
    memo TEXT
);

-- 失敗記録テーブル
CREATE TABLE IF NOT EXISTS re (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    improvement TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    likes INTEGER DEFAULT 0
);

-- 失敗記録に対する「いいね」テーブル
CREATE TABLE IF NOT EXISTS re_likes (
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    re_id INTEGER REFERENCES re(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, re_id)
);

ALTER TABLE re ADD COLUMN ai_feedback TEXT;
ALTER TABLE re ADD COLUMN is_shared BOOLEAN DEFAULT FALSE;
ALTER TABLE re ADD COLUMN re_analysis TEXT;
ALTER TABLE users ADD COLUMN reminder_time TIME DEFAULT '18:00';  -- 学習リマインド時間
ALTER TABLE users ADD COLUMN last_recovery_notify DATE;            -- 最後に再開通知を送った日



