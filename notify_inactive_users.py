import psycopg2
from datetime import datetime, timedelta
from email.mime.text import MIMEText
import smtplib
from dotenv import load_dotenv
import os

load_dotenv()
db_config = {
    'host': os.environ.get('DB_HOST'),
    'database': os.environ.get('DB_NAME'),
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD'),
    'port': os.environ.get('DB_PORT', 5432),  # ポートが空なら5432をデフォルトに
    'sslmode': 'require'
}

# ローカルPostgreSQLの接続設定
"""
load_dotenv()

db_config = {
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'port': os.getenv('DB_PORT'),
    'sslmode': 'require'
}
"""


# 接続
conn = psycopg2.connect(**db_config)
cursor = conn.cursor()

# 7日以上記録がないユーザーを取得
cursor.execute('''
    SELECT u.email, u.username
    FROM users u
    LEFT JOIN (
        SELECT user_id, MAX(study_date) AS last_date
        FROM record
        GROUP BY user_id
    ) r ON u.id = r.user_id
    WHERE
      (r.last_date IS NULL OR r.last_date < CURRENT_DATE - u.failure_days * INTERVAL '1 day')
      AND u.email IS NOT NULL
''')

users_to_notify = cursor.fetchall()
conn.close()

# メール送信
for email, username in users_to_notify:
    if not email:
        continue  # メール未登録ならスキップ

    msg = MIMEText(f"{username}さん、最近学習記録がありません。続けてみませんか？")
    msg['Subject'] = '【学習記録アプリ】1週間記録がありません'
    msg['From'] = 's231w015@s.iwate-pu.ac.jp'
    msg['To'] = email

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.starttls()
            smtp.login('yuumnbo@gmail.com', 'tqbz doiy qxca ovqg')
            smtp.send_message(msg)
            print(f"✔️ 送信成功: {email}")
    except Exception as e:
        print(f"❌ 送信失敗: {email}, エラー: {e}")
