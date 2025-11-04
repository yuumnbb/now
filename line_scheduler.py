import psycopg2
import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
db_config = {
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'port': os.getenv('DB_PORT', 5432),
    'sslmode': 'require'
}

def send_line_message(user_id, message):
    """個別LINEメッセージ送信"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}]
    }
    res = requests.post(url, headers=headers, json=payload)
    print(f"[{res.status_code}] {res.text}")

def main():
    now = datetime.now()
    today = now.date()
    current_time = now.strftime("%H:%M")

    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()

    # ① 各自の設定時間に送る学習リマインダー
    cursor.execute('''
        SELECT username, line_user_id, reminder_time
        FROM users
        WHERE line_user_id IS NOT NULL
          AND TO_CHAR(reminder_time, 'HH24:MI') = %s
    ''', (current_time,))
    daily_users = cursor.fetchall()

    for username, line_user_id, reminder_time in daily_users:
        message = (
            f"{username}さん、今日も学習を続けましょう！📘\n"
            "小さな行動でも積み重ねが大切です。"
        )
        send_line_message(line_user_id, message)
        print(f"📩 学習リマインド送信 → {username} さん ({reminder_time})")

    # ② failure_daysを超えた人に2日に1回再開通知
    cursor.execute('''
        SELECT u.id, u.username, u.line_user_id, u.failure_days, u.last_recovery_notify,
               COALESCE(r.last_date, '1900-01-01') AS last_date
        FROM users u
        LEFT JOIN (
            SELECT user_id, MAX(study_date) AS last_date
            FROM record
            GROUP BY user_id
        ) r ON u.id = r.user_id
        WHERE
          (r.last_date IS NULL OR r.last_date < CURRENT_DATE - u.failure_days * INTERVAL '1 day')
          AND u.line_user_id IS NOT NULL
    ''')
    recovery_targets = cursor.fetchall()

    for user_id, username, line_user_id, failure_days, last_notify, last_date in recovery_targets:
        # 前回送信から2日以内ならスキップ
        if last_notify and (today - last_notify).days < 2:
            continue

        message = (
            f"{username}さん、{failure_days}日以上学習記録がありません。\n"
            "でも大丈夫です。失敗も成長の一部です🌱\n"
            "もう一度AIの『回復プログラム』で再スタートしてみませんか？\n\n"
            "▶ 回復プログラムはこちら：\n"
            "https://あなたのアプリURL/recovery"
        )
        send_line_message(line_user_id, message)

        # 通知日を更新
        cursor.execute('UPDATE users SET last_recovery_notify = %s WHERE id = %s', (today, user_id))
        conn.commit()
        print(f"🔁 再開リマインド送信 → {username} さん")

    conn.close()

if __name__ == "__main__":
    print(f"⏰ 実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    main()
