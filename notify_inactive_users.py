import psycopg2
from datetime import datetime, timedelta
from email.mime.text import MIMEText
import smtplib

# PostgreSQLの接続設定
db_config = {
    'host': '127.0.0.1',  # Dockerのホスト
    'database': 'postgres',  # デフォルトのデータベース名
    'user': 'postgres',
    'password': 'postgres',
    'port': 25434          # docker-composeで指定したポート
}

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
    WHERE r.last_date IS NULL OR r.last_date < %s
''', (datetime.now() - timedelta(days=7),))

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
