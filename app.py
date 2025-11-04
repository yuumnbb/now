from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import DictCursor
import json
from datetime import datetime, timedelta,date,time
import google.generativeai as genai
from dotenv import load_dotenv
import os
import requests

genai.configure(api_key="AIzaSyARwdaBw94QJprFI2IcTfOClwI15a0fKZs")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")

app = Flask(__name__)
app.secret_key = 'your_secret_key'

@app.before_request
def sanitize_session():
    if 'user' in session:
        safe_user = {}
        for k, v in session['user'].items():
            if isinstance(v, time):
                safe_user[k] = v.strftime("%H:%M")
            elif isinstance(v, datetime):
                safe_user[k] = v.isoformat()
            else:
                safe_user[k] = str(v)
        session['user'] = safe_user

"""
db_config = {
    'host': '127.0.0.1',  # Dockerのホスト
    'database': 'postgres',  # デフォルトのデータベース名
    'user': 'postgres',
    'password': 'postgres',
    'port': 25434          # docker-composeで指定したポート
}
"""

load_dotenv()

db_config = {
    'host': os.environ.get('DB_HOST'),
    'database': os.environ.get('DB_NAME'),
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD'),
    'port': os.environ.get('DB_PORT', 5432),  # ポートが空なら5432をデフォルトに
    'sslmode': 'require'
}

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

# データベースの初期化
def init_db():
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            goal TEXT,
            weekly_target INTEGER, 
            small_action TEXT,
            anchor TEXT,
            failure_days INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS record (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            study_date DATE NOT NULL,
            study_time INTEGER NOT NULL,
            memo TEXT,
            next_study_date DATE,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()


@app.route('/', methods=['GET', 'POST'])
def login():
    message = None  # ログイン失敗メッセージ表示用

    if request.method == 'POST':
        username = request.form['name']
        password = request.form['password']

        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor(cursor_factory=DictCursor)

        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password'], password):
            # 🔹 psycopg2.DictRow → Python dict に変換しつつ time型を文字列化
            clean_user = {}
            for k, v in dict(user).items():
                if isinstance(v, time): # time クラスを使用
                    clean_user[k] = v.strftime("%H:%M")
                else:
                    clean_user[k] = v
            session['user'] = clean_user


            # goalが未設定なら即時 setting に遷移
            if not user.get('goal'):
                conn.close()
                return redirect(url_for('setting'))

            # 最後の記録日を取得
            cursor.execute('''
                SELECT MAX(study_date) AS last_study_date
                FROM record
                WHERE user_id = %s
            ''', (user['id'],))
            last_record = cursor.fetchone()
            last_date = last_record['last_study_date']

            failure_days = user.get('failure_days') or 3

            if last_date:
                last_date = datetime.combine(last_date, datetime.min.time())
                days_since_last_record = (datetime.now() - last_date).days

                if days_since_last_record > failure_days:
                    conn.close()
                    return redirect(url_for('recovery'))

            # その他の設定が未入力でも setting に誘導
            if not user.get('small_action') or not user.get('anchor'):
                conn.close()
                return redirect(url_for('setting'))

            conn.close()
            return redirect(url_for('mypage'))

        else:
            # 認証失敗時は flash を使わず、テンプレートに直接渡す
            message = 'ユーザー名またはパスワードが間違っています。'
            conn.close()

    return render_template('login.html', message=message)





# 新規登録ページ
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email'] 
        hashed_password = generate_password_hash(password)

        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        try:
            # goal を指定していない場合、NULL が設定されるようにする
            cursor.execute(
                'INSERT INTO users (username, password, email) VALUES (%s, %s, %s)',
                (username, hashed_password, email)
            )
            conn.commit()
            conn.close()

            flash('登録が完了しました。設定を入力してください。')
            return redirect(url_for('setting'))
        except psycopg2.Error:
            flash('このユーザー名またはメールアドレスは既に使用されています。')
            conn.close()
            return render_template('signup.html', message='このユーザー名またはメールアドレスは既に使用されています。')
    return render_template('signup.html', message='')

@app.route('/resilience')
def resilience():
    if 'user' not in session:
        flash('ログインしてください。')
        return redirect(url_for('login'))

    user_id = session['user']['id']
    order_by = request.args.get('order', 'new')
    page = int(request.args.get('page', 1))
    per_page = 10
    offset = (page - 1) * per_page

    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor(cursor_factory=DictCursor)

    # 自分の記録（全件）
    cursor.execute('''
        SELECT id, reason, improvement, created_at, likes, ai_feedback
        FROM re
        WHERE user_id = %s
        ORDER BY created_at DESC
    ''', (user_id,))
    my_recovery_data = cursor.fetchall()

    # 最新の1件だけ抽出してmy_feedbackとして渡す
    my_feedback = my_recovery_data[0] if my_recovery_data else None

    # 自分の継続日数を算出
    cursor.execute('''
        SELECT MIN(study_date) FILTER (WHERE study_date >= COALESCE((
            SELECT MAX(created_at::date) FROM re WHERE user_id = %s
        ), '1900-01-01')) AS first_study,
               MAX(study_date) AS last_study
        FROM record
        WHERE user_id = %s
    ''', (user_id, user_id))
    result = cursor.fetchone()
    if result['first_study'] and result['last_study']:
        my_streak = (result['last_study'] - result['first_study']).days + 1
    else:
        my_streak = 0

    # 全体の継続日数マップ作成（user_id → streak）
    cursor.execute('''
        SELECT s.user_id,
               MIN(s.study_date) FILTER (WHERE s.study_date >= COALESCE(r.latest_re, '1900-01-01')) AS first_study,
               MAX(s.study_date) AS last_study
        FROM record s
        LEFT JOIN (
            SELECT user_id, MAX(created_at::date) AS latest_re
            FROM re
            GROUP BY user_id
        ) r ON s.user_id = r.user_id
        GROUP BY s.user_id
    ''')
    streak_data = cursor.fetchall()
    streak_map = {}
    for row in streak_data:
        if row['first_study'] and row['last_study']:
            streak_map[row['user_id']] = (row['last_study'] - row['first_study']).days + 1
        else:
            streak_map[row['user_id']] = 0

    # 投稿の取得
    if order_by == 'popular':
        cursor.execute('''
            SELECT re.id, re.user_id, users.username, re.reason, re.improvement, re.created_at, re.likes
            FROM re
            JOIN users ON re.user_id = users.id
            WHERE re.is_shared = TRUE
            ORDER BY re.likes DESC, re.created_at DESC
            LIMIT %s OFFSET %s
        ''', (per_page, offset))
        recovery_data = [dict(row) for row in cursor.fetchall()]
        for row in recovery_data:
            row['streak'] = streak_map.get(row['user_id'], 0)
    elif order_by == 'streak':
        cursor.execute('''
            SELECT re.id, re.user_id, users.username, re.reason, re.improvement, re.created_at, re.likes
            FROM re
            JOIN users ON re.user_id = users.id
            WHERE re.is_shared = TRUE
        ''')
        all_data = [dict(row) for row in cursor.fetchall()]
        for row in all_data:
            row['streak'] = streak_map.get(row['user_id'], 0)
        all_data.sort(key=lambda x: x['streak'], reverse=True)
        recovery_data = all_data[offset:offset + per_page]
    else:
        cursor.execute('''
            SELECT re.id, re.user_id, users.username, re.reason, re.improvement, re.created_at, re.likes
            FROM re
            JOIN users ON re.user_id = users.id
            WHERE re.is_shared = TRUE
            ORDER BY re.created_at DESC
            LIMIT %s OFFSET %s
        ''', (per_page, offset))
        recovery_data = [dict(row) for row in cursor.fetchall()]
        for row in recovery_data:
            row['streak'] = streak_map.get(row['user_id'], 0)

    # ページ数取得
    cursor.execute('SELECT COUNT(*) FROM re')
    total_records = cursor.fetchone()[0]
    total_pages = (total_records + per_page - 1) // per_page

    # いいね済の投稿
    cursor.execute('SELECT re_id FROM re_likes WHERE user_id = %s', (user_id,))
    liked_ids = [row['re_id'] for row in cursor.fetchall()]
    conn.close()

    return render_template('resilience.html',
                           my_recovery_data=my_recovery_data,
                           recovery_data=recovery_data,
                           my_streak=my_streak,
                           order_by=order_by,
                           liked_ids=liked_ids,
                           page=page,
                           total_pages=total_pages,
                           my_feedback=my_feedback)



@app.route('/setting', methods=['GET', 'POST'])
def setting():
    if 'user' not in session:
        flash("ログインしてください。")
        return redirect(url_for('login'))

    user_id = session['user']['id']

    if request.method == 'POST':
        goal = request.form['goal']
        weekly_target = request.form['weekly_target']
        small_action = request.form['small_action']
        anchor = request.form['anchor']
        failure_days = request.form['failure_days']
        reminder_time = request.form.get('reminder_time') or '18:00'  # デフォルト18時

        # 🔹 time型なら文字列化
        if isinstance(reminder_time, datetime.time):
            reminder_time = reminder_time.strftime("%H:%M")
        else:
            reminder_time = str(reminder_time)

        try:
            conn = psycopg2.connect(**db_config)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users
                SET goal = %s,
                    weekly_target = %s,
                    small_action = %s,
                    anchor = %s,
                    failure_days = %s,
                    reminder_time = %s
                WHERE id = %s
            ''', (goal, weekly_target, small_action, anchor, failure_days, reminder_time, user_id))
            conn.commit()
            conn.close()

            # 🔹 セッション更新時にも確実に文字列化
            session_user = session.get('user', {})
            session_user.update({
                'goal': goal,
                'weekly_target': weekly_target,
                'small_action': small_action,
                'anchor': anchor,
                'failure_days': failure_days,
                'reminder_time': str(reminder_time)
            })

            # time型が混じらないように
            session['user'] = {
                k: (v.strftime("%H:%M") if isinstance(v, datetime.time) else v)
                for k, v in session_user.items()
            }

            flash("設定を保存しました。")
            return redirect(url_for('mypage'))

        except Exception as e:
            print("設定保存エラー:", e)
            flash("設定の保存中にエラーが発生しました。")
            return render_template('setting.html', message='エラーが発生しました。')

    # GETリクエスト時
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute('''
            SELECT goal, weekly_target, small_action, anchor, failure_days, reminder_time
            FROM users
            WHERE id = %s
        ''', (user_id,))
        setting = cursor.fetchone()
        conn.close()

        # 🔹 reminder_time が datetime.time 型なら文字列に変換
        if setting and isinstance(setting['reminder_time'], datetime.time):
            setting['reminder_time'] = setting['reminder_time'].strftime("%H:%M")

    except Exception as e:
        print("設定取得エラー:", e)
        setting = None

    return render_template('setting.html', setting=setting, message='')




# マイページ

@app.route('/mypage')
def mypage():
    if 'user' not in session:
        flash('ログインしてください。')
        return redirect(url_for('login'))

    user_id = session['user']['id']

    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor(cursor_factory=DictCursor)

    # 設定情報の取得
    cursor.execute('SELECT goal, weekly_target, small_action, anchor, failure_days FROM users WHERE id = %s', (user_id,))
    setting = cursor.fetchone()

    # 学習記録を取得
    cursor.execute('''
        SELECT study_date, study_time, memo, category_id
        FROM record
        WHERE user_id = %s
        ORDER BY study_date ASC
    ''', (user_id,))
    records = cursor.fetchall()

    # 継続日数計算用の記録抽出
    if records:
        first_study_date = records[0]['study_date']
        latest_study_date = records[-1]['study_date']
    else:
        first_study_date = latest_study_date = None

    # 最終回復実行日を取得
    cursor.execute('''
        SELECT MAX(created_at::date) AS latest_recovery_date
        FROM re
        WHERE user_id = %s
    ''', (user_id,))
    result = cursor.fetchone()
    latest_recovery_date = result['latest_recovery_date'] if result else None

    # 継続日数の計算
    if first_study_date and latest_study_date:
        if latest_recovery_date and latest_recovery_date < latest_study_date:
            continuity_days = (latest_study_date - latest_recovery_date).days
        else:
            continuity_days = (latest_study_date - first_study_date).days
    else:
        continuity_days = 0

    # カテゴリ名取得
    cursor.execute('''
        SELECT id, category_name FROM study_categories WHERE user_id = %s
    ''', (user_id,))
    category_map = {row['id']: row['category_name'] for row in cursor.fetchall()}

    # 次回予定は使用しない（削除）
    study_records = []
    for r in records:
        study_records.append({
            'study_date': r['study_date'],
            'study_time': r['study_time'],
            'memo': r['memo'],
            'category_id': r['category_id'],
            'category_name': category_map.get(r['category_id'], '未分類')
        })

    conn.close()

    # 色設定（例：カテゴリID 1〜10まで）
    category_colors = {
        1: "#007bff", 2: "#28a745", 3: "#ffc107", 4: "#dc3545", 5: "#6610f2",
        6: "#17a2b8", 7: "#fd7e14", 8: "#20c997", 9: "#6f42c1", 10: "#e83e8c"
    }

    return render_template('mypage.html',
                           user=session['user'],
                           setting=setting,
                           continuity_days=continuity_days,
                           study_records=study_records,
                           category_colors=category_colors)



from flask import jsonify


@app.route('/record', methods=['GET', 'POST'])
def record():
    if 'user' not in session:
        return redirect(url_for('login'))

    user_id = session['user']['id']
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor(cursor_factory=DictCursor)

    if request.method == 'POST':
        if request.is_json:
            # JSからのカテゴリ追加
            data = request.get_json()
            new_category = data.get('name', '').strip()
            if not new_category:
                return jsonify({'success': False, 'message': 'カテゴリ名を入力してください。'}), 400
            cursor.execute('SELECT 1 FROM study_categories WHERE user_id = %s AND LOWER(category_name) = LOWER(%s)', (user_id, new_category))
            if cursor.fetchone():
                return jsonify({'success': False, 'message': 'そのカテゴリは既に存在します。'}), 400
            cursor.execute('INSERT INTO study_categories (user_id, category_name) VALUES (%s, %s) RETURNING id', (user_id, new_category))
            new_id = cursor.fetchone()['id']
            conn.commit()
            return jsonify({'success': True, 'id': new_id}), 200

        # 学習記録フォームからのPOST
        study_date = request.form.get('study_date')
        study_time = request.form.get('study_time')
        category_id = request.form.get('category_id')
        memo = request.form.get('memo')

        if not study_time or not study_time.isdigit() or int(study_time) <= 0:
            flash("学習時間は1分以上の数字で入力してください。")
            return redirect(url_for('record'))

        cursor.execute('''
            INSERT INTO record (user_id, study_date, study_time, category_id, memo)
            VALUES (%s, %s, %s, %s, %s)
        ''', (user_id, study_date, int(study_time), category_id, memo))
        conn.commit()
        conn.close()
        return redirect(url_for('mypage'))

    # GET: 初期表示処理
    cursor.execute('SELECT id, category_name FROM study_categories WHERE user_id = %s ORDER BY category_name', (user_id,))
    categories = cursor.fetchall()
    conn.close()

    return render_template('record.html', categories=categories, today=date.today().isoformat())


from flask import render_template, session, redirect, url_for, flash
import psycopg2
from psycopg2.extras import DictCursor
import json

from flask import request

@app.route('/analysis')
def analysis():
    if 'user' not in session:
        flash('ログインしてください。')
        return redirect(url_for('login'))

    user_id = session['user']['id']
    period = request.args.get('period', 'week')
    offset = int(request.args.get('offset', 0))

    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute('''
        SELECT study_date, study_time
        FROM record
        WHERE user_id = %s
        ORDER BY study_date ASC
    ''', (user_id,))
    records = cursor.fetchall()
    conn.close()

    if not records:
        return render_template('analysis.html', error="学習記録がありません。", period=period, offset=offset)

    import pandas as pd
    from datetime import datetime, timedelta
    import json

    df = pd.DataFrame(records, columns=['study_date', 'study_time'])
    df['study_date'] = pd.to_datetime(df['study_date'])
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    max_time = int(df['study_time'].max()) if not df.empty else 60

    def generate_date_range(start, end):
        return pd.date_range(start=start, end=end)

    weekly_data, monthly_data, yearly_data = [], [], []
    weekly_avg = monthly_avg = yearly_avg = 0

    if period == 'week':
        end_date = today - timedelta(days=7 * offset)
        start_date = end_date - timedelta(days=6)
        full_range = generate_date_range(start_date, end_date)
        target_df = df[(df['study_date'] >= start_date) & (df['study_date'] <= end_date)]
        filled_df = pd.DataFrame({'study_date': full_range})
        merged = pd.merge(filled_df, target_df, on='study_date', how='left').fillna(0)
        weekly_data = merged.to_dict(orient='records')
        weekly_avg = round(merged['study_time'].mean(), 1)

    if period == 'month':
        end_date = today - timedelta(days=30 * offset)
        start_date = end_date - timedelta(days=29)
        full_range = generate_date_range(start_date, end_date)
        target_df = df[(df['study_date'] >= start_date) & (df['study_date'] <= end_date)]
        filled_df = pd.DataFrame({'study_date': full_range})
        merged = pd.merge(filled_df, target_df, on='study_date', how='left').fillna(0)
        monthly_data = merged.to_dict(orient='records')
        monthly_avg = round(merged['study_time'].mean(), 1)

    if period == 'year':
        df['year_month'] = df['study_date'].dt.to_period('M').astype(str)
        recent_months = pd.period_range(end=today, periods=12, freq='M').astype(str)
        month_df = pd.DataFrame({'year_month': recent_months})
        grouped = df.groupby('year_month')['study_time'].mean().reset_index()
        merged = pd.merge(month_df, grouped, on='year_month', how='left').fillna(0)
        
        # ✅ ここでリネームしてから平均を算出
        merged = merged.rename(columns={'year_month': 'label', 'study_time': 'value'})
        yearly_data = merged.to_dict(orient='records')
        yearly_avg = round(merged['value'].mean(), 1)


    return render_template('analysis.html',
                           weekly_data=json.dumps(weekly_data, default=str),
                           weekly_avg=weekly_avg,
                           monthly_data=json.dumps(monthly_data, default=str),
                           monthly_avg=monthly_avg,
                           yearly_data=json.dumps(yearly_data, default=str),
                           yearly_avg=yearly_avg,
                           max_time=max_time,
                           period=period,
                           offset=offset)




USE_GEMINI_API = True  # 必要に応じて False に

@app.route('/recovery', methods=['GET', 'POST'])
def recovery():
    if 'user' not in session:
        return jsonify({'error': 'ログインしてください。'}), 401

    user = session['user']
    user_id = user['id']
    goal = user.get('goal') or "学習目標"
    weekly_target = user.get('weekly_target', 3)

    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            reason = data.get('reason', '').strip()
            improvement = data.get('improvement', '').strip()
            is_shared = bool(data.get('is_shared', False))

            if not reason or not improvement:
                return jsonify({'error': 'すべての項目を入力してください。'}), 400

            try:
                advice = generate_feedback_advice(reason, improvement)
            except Exception as e:
                print("Gemini API Error (advice):", e)
                advice = "AIアドバイスの生成に失敗しました。"

            try:
                analysis = generate_gemini_analysis(user_id, goal, weekly_target)
            except Exception as e:
                print("Gemini API Error (analysis):", e)
                analysis = "AIによる分析の生成に失敗しました。"

            # データベースに保存
            conn = psycopg2.connect(**db_config)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO re (user_id, reason, improvement, ai_feedback, re_analysis, is_shared, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ''', (user_id, reason, improvement, advice, analysis, is_shared))
            conn.commit()
            conn.close()

            return jsonify({"advice": advice})

        return jsonify({'error': 'Unsupported Media Type'}), 415

    suggested_result = generate_gemini_analysis(user_id, goal, weekly_target) if USE_GEMINI_API else None
    return render_template('re.html',
                           suggested_result=suggested_result,
                           reason='',
                           improvement='')

def generate_gemini_analysis(user_id, goal, weekly_target):
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor(cursor_factory=DictCursor)

    cursor.execute('''
        SELECT study_date, study_time
        FROM record
        WHERE user_id = %s
        ORDER BY study_date
    ''', (user_id,))
    records = cursor.fetchall()

    days = set()
    total_time = 0
    for r in records:
        days.add(r['study_date'])
        total_time += r['study_time']

    actual_days = len(days)
    avg_time = round(total_time / actual_days) if actual_days else 0

    # 継続日数
    if records:
        first_study_date = records[0]['study_date']
        latest_study_date = records[-1]['study_date']
    else:
        first_study_date = latest_study_date = None

    cursor.execute('''
        SELECT MAX(created_at::date) AS latest_recovery_date
        FROM re
        WHERE user_id = %s
    ''', (user_id,))
    result = cursor.fetchone()
    latest_recovery_date = result['latest_recovery_date'] if result else None

    if first_study_date and latest_study_date:
        if latest_recovery_date and latest_recovery_date < latest_study_date:
            continuity_days = (latest_study_date - latest_recovery_date).days
        else:
            continuity_days = (latest_study_date - first_study_date).days
    else:
        continuity_days = 0

    # 直近10件の学習内容
    cursor.execute('''
        SELECT TO_CHAR(r.study_date, 'MM/DD') AS date, c.category_name
        FROM record r
        JOIN study_categories c ON r.category_id = c.id
        WHERE r.user_id = %s
        ORDER BY r.study_date DESC
        LIMIT 10
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()

    record_text = ', '.join([f"{row['date']} {row['category_name']}" for row in rows])

    prompt = f"""
学習記録をもとに分析してください。
・学習目的　{goal}
・週の目標日数　{weekly_target}日
・実際の週の平均日数　{actual_days}日
・学習日と学習内容　{record_text}
・学習日の平均学習時間　{avg_time}分
・継続日数　{continuity_days}日

分析後、学習目的に対する習慣化を失敗する原因と対策の例を2件ずつ記載して。原因と対策は対応させて、学習目標に対応する専門性も意識して。

条件：
学習習慣に失敗してしまった人のデータという面を考慮して。
自分の失敗した原因と解決案を導き出してあげる手助けです。
Atomic Habitsとレジリエンスの観点を意識して答えて。
AtomicHabitsはきっかけ、欲求、反応、報酬のサイクルでポイントとしては、小さく行動していくこと、回数を増やしていくこと。
レジリエンスは・ポジティブな感情 ・内的資源や外的資源の活用 ・自尊感情及び自己効力感が重要。 
この理論を知らない人が見るので、専門用語は伏せて答えて。
学習時間に関して5分以上は短くないので「学習時間が短い」という表現は禁止。
"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    response = model.generate_content(prompt)
    return response.text.strip()

def generate_feedback_advice(reason, improvement):
    if not USE_GEMINI_API:
        return f"あなたの原因「{reason}」と対策「{improvement}」は素晴らしい気づきです！\nさらにリマインダーを設けたり、毎回終わりに振り返る習慣を加えるとより効果的です。"

    prompt = f"""
原因：
{reason}

対策：
{improvement}

こちらはユーザーが考えた原因と対策です。内容を尊重しつつ、より効果的にするためのアドバイスを簡潔に日本語で記載してください。
アドバイスには「こうするとさらに良い」など肯定的な視点を含めてください。
また上記に加えて、すぐ学習できる環境づくり（教材の準備、場所の確保など）も促してください。
"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    response = model.generate_content(prompt)
    return response.text.strip()



import re

@app.template_filter('regex_replace')
def regex_replace(s, find, replace, ignorecase=True, multiline=False):
    flags = re.IGNORECASE if ignorecase else 0
    if multiline:
        flags |= re.MULTILINE
    return re.sub(find, replace, s, flags=flags)



@app.route('/like_recovery/<int:re_id>', methods=['POST'])
def like_recovery(re_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user']['id']

    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()

    # すでにいいねしているか確認
    cursor.execute('SELECT 1 FROM re_likes WHERE user_id = %s AND re_id = %s', (user_id, re_id))
    already_liked = cursor.fetchone()

    if not already_liked:
        # re_likes に記録 + re テーブルの likes カウント増やす
        cursor.execute('INSERT INTO re_likes (user_id, re_id) VALUES (%s, %s)', (user_id, re_id))
        cursor.execute('UPDATE re SET likes = likes + 1 WHERE id = %s', (re_id,))
        conn.commit()

    # 最新のlike数を取得して返す
    cursor.execute('SELECT likes FROM re WHERE id = %s', (re_id,))
    updated_likes = cursor.fetchone()[0]
    conn.close()

    return jsonify({'success': True, 'likes': updated_likes})

@app.route("/line/webhook", methods=["POST"])
def line_webhook():
    body = request.get_json()
    events = body.get("events", [])

    for event in events:
        if event["type"] == "follow":  # ← ユーザーが友達追加した時
            line_user_id = event["source"]["userId"]

            # 例：LINE表示名を取得
            profile_url = "https://api.line.me/v2/bot/profile/" + line_user_id
            headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
            profile = requests.get(profile_url, headers=headers).json()
            display_name = profile.get("displayName")

            # 仮にログイン中のFlaskユーザーと紐付けるなら：
            if 'user' in session:
                user_id = session['user']['id']
                conn = psycopg2.connect(**db_config)
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET line_user_id = %s WHERE id = %s', (line_user_id, user_id))
                conn.commit()
                conn.close()
                print(f"✅ {display_name}（LINE）とユーザーID {user_id} を紐付けました。")

            # 自動メッセージ送信
            reply_url = "https://api.line.me/v2/bot/message/push"
            payload = {
                "to": line_user_id,
                "messages": [
                    {"type": "text", "text": f"{display_name}さん、アプリとLINEが連携されました！📲"}
                ]
            }
            requests.post(reply_url, headers={"Authorization": f"Bearer {LINE_TOKEN}",
                                              "Content-Type": "application/json"}, json=payload)

    return jsonify({"status": "ok"})


# ログアウト
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()  # データベース初期化
    app.run(debug=True)
