from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import DictCursor
import json
from datetime import datetime, timedelta, date, time
import os
import requests
import base64
import uuid
import re

# 環境変数の読み込み
from dotenv import load_dotenv
load_dotenv()

# LINE Botの認証情報
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# LINEログインの認証情報 (LINE Developersで設定した値に置き換えてください)
LINE_CHANNEL_ID = os.getenv("LINE_LOGIN_CHANNEL_ID")
LINE_LOGIN_CHANNEL_SECRET = os.getenv("LINE_LOGIN_CHANNEL_SECRET")
# 🚨 Azure環境でのHTTPSを想定し、デフォルトをHTTPSに設定
LINE_REDIRECT_URI = os.getenv("LINE_REDIRECT_URI", "https://studyhabits-gbevh2bgdygjgtag.japaneast-01.azurewebsites.net/line/callback")

# Gemini APIの設定
import google.generativeai as genai
API =os.getenv("API")
genai.configure(api_key=API)

app = Flask(__name__)
# ⚠️ 本番環境ではより強力な鍵を使用してください
app.secret_key = 'your_secret_key'

# データベース設定
db_config = {
    'host': os.environ.get('DB_HOST'),
    'database': os.environ.get('DB_NAME'),
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD'),
    'port': os.environ.get('DB_PORT', 5432),
    'sslmode': 'require'
}

@app.before_request
def sanitize_session():
    """リクエスト前にセッション内のdatetime/timeオブジェクトを文字列に変換しTypeErrorを防ぐ"""
    if 'user' in session:
        safe_user = {}
        for k, v in session['user'].items():
            # time型を文字列に変換
            if isinstance(v, time):
                safe_user[k] = v.strftime("%H:%M")
            # datetime型を文字列に変換 (date型はdatetimeの親クラスなのでdatetimeでチェック)
            elif isinstance(v, datetime):
                safe_user[k] = v.isoformat()
            else:
                safe_user[k] = v
        session['user'] = safe_user

# データベースの初期化
def init_db():
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
    except Exception as e:
        print(f"データベース接続失敗（init_db）: {e}")
        return

    # ユーザーテーブル (LINE ID, 通知日を追加)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE, 
            line_user_id VARCHAR(255) UNIQUE, -- LINE連携用
            goal TEXT,
            weekly_target INTEGER, 
            small_action TEXT,
            anchor TEXT,
            failure_days INTEGER,
            reminder_time TIME, -- TIME型に修正
            last_recovery_notify DATE -- リマインド通知の最終実行日
        )
    ''')
    # 学習記録テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS record (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            study_date DATE NOT NULL,
            study_time INTEGER NOT NULL,
            memo TEXT,
            category_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')
    # カテゴリテーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS study_categories (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            category_name VARCHAR(255) NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            UNIQUE (user_id, category_name)
        )
    ''')
    # 回復記録テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS re (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            improvement TEXT NOT NULL,
            ai_feedback TEXT,
            re_analysis TEXT,
            is_shared BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            likes INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')
    # いいねテーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS re_likes (
            user_id INTEGER NOT NULL,
            re_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, re_id),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (re_id) REFERENCES re (id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()


@app.route('/', methods=['GET', 'POST'])
def login():
    message = None

    if request.method == 'POST':
        username = request.form['name']
        password = request.form['password']

        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor(cursor_factory=DictCursor)

        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password'], password):
            # psycopg2.DictRow → Python dict に変換しつつ time型を文字列化
            clean_user = {}
            for k, v in dict(user).items():
                if isinstance(v, time):
                    clean_user[k] = v.strftime("%H:%M")
                else:
                    clean_user[k] = v
            session['user'] = clean_user

            if not user.get('goal'):
                conn.close()
                return redirect(url_for('setting'))

            cursor.execute('''
                SELECT MAX(study_date) AS last_study_date
                FROM record
                WHERE user_id = %s
            ''', (user['id'],))
            last_record = cursor.fetchone()
            last_date = last_record['last_study_date']

            failure_days = user.get('failure_days') or 3

            if last_date:
                # DBから取得した日付オブジェクトと現在のdatetimeオブジェクトを比較するため、datetime型に変換
                last_date_dt = datetime.combine(last_date, datetime.min.time()).date()
                days_since_last_record = (date.today() - last_date_dt).days

                if days_since_last_record > failure_days:
                    conn.close()
                    return redirect(url_for('recovery'))

            if not user.get('small_action') or not user.get('anchor'):
                conn.close()
                return redirect(url_for('setting'))

            conn.close()
            return redirect(url_for('mypage'))

        else:
            message = 'ユーザー名またはパスワードが間違っています。'
            conn.close()

    return render_template('login.html', message=message)


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
            # emailカラムを追加
            cursor.execute(
                'INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id',
                (username, hashed_password, email)
            )
            user_id = cursor.fetchone()[0]

            # ユーザー作成と同時にデフォルトのカテゴリを作成
            default_categories = ["仕事", "プログラミング", "資格試験", "その他"]
            for name in default_categories:
                 cursor.execute(
                     'INSERT INTO study_categories (user_id, category_name) VALUES (%s, %s)',
                     (user_id, name)
                 )

            conn.commit()
            conn.close()

            flash('登録が完了しました。設定を入力してください。')
            return redirect(url_for('setting'))
        except psycopg2.errors.UniqueViolation:
            flash('このユーザー名またはメールアドレスは既に使用されています。')
            conn.close()
            return render_template('signup.html', message='このユーザー名またはメールアドレスは既に使用されています。')
        except Exception as e:
            print(f"サインアップエラー: {e}")
            flash('サインアップ中に予期せぬエラーが発生しました。')
            conn.close()
            return render_template('signup.html', message='エラーが発生しました。')

    return render_template('signup.html', message='')

# --- LINE 連携エンドポイント ---

@app.route("/line/start_auth")
def line_start_auth():
    if 'user' not in session:
        flash('LINE連携を開始するにはログインが必要です。', 'error')
        return redirect(url_for('login'))

    user_id = session['user']['id']

    # 1. CSRF対策のstateを生成し、セッションに保存
    state = str(uuid.uuid4())
    session['line_auth_state'] = state
    
    # 2. アプリ側のユーザーIDをセッションに一時保存
    session['line_link_user_id'] = user_id

    # 3. LINE認証URLを構築
    auth_url = 'https://access.line.me/oauth2/v2.1/authorize'
    params = {
        'response_type': 'code',
        'client_id': LINE_CHANNEL_ID,
        'redirect_uri': LINE_REDIRECT_URI,
        'state': state,
        'scope': 'profile openid', # ユーザーID取得に必須のスコープ
        'prompt': 'consent', # 毎回同意画面を表示させる
    }

    # URLの生成とリダイレクト
    import urllib.parse
    query_string = urllib.parse.urlencode(params)
    return redirect(f"{auth_url}?{query_string}")


@app.route('/line/callback')
def line_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    
    # 1. stateの検証 (CSRF対策)
    if state != session.pop('line_auth_state', None):
        flash("LINE認証の状態が一致しませんでした。セキュリティエラー。", 'error')
        return redirect(url_for('setting'))
    
    # 2. 認証がキャンセルされたかチェック
    if not code:
        flash("LINE認証がキャンセルされました。", 'warning')
        return redirect(url_for('setting'))

    # 3. アプリ側のユーザーIDを取得
    user_id = session.pop('line_link_user_id', None)
    if not user_id:
        flash("LINE連携中にログイン情報が失われました。再度ログインしてください。", 'error')
        return redirect(url_for('login'))

    try:
        # 4. トークン取得API呼び出し (IDトークン、アクセス/リフレッシュトークンを交換)
        token_url = 'https://api.line.me/oauth2/v2.1/token'
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        payload = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': LINE_REDIRECT_URI,
            'client_id': LINE_CHANNEL_ID,
            'client_secret': LINE_LOGIN_CHANNEL_SECRET # ログインチャネルのシークレットを使用
        }
        
        token_response = requests.post(token_url, headers=headers, data=payload)
        token_data = token_response.json()
        
        if 'id_token' not in token_data:
            # トークン取得失敗
            app.logger.error(f"[LINE認証エラー] トークン交換失敗: {token_data.get('error_description', token_data.get('error', 'Unknown Error'))}")
            flash('LINE連携に失敗しました。認証サーバーでエラーが発生しました。設定とコールバックURLを確認してください。', 'error')
            return redirect(url_for('setting'))

        # 5. IDトークンからユーザーID（sub）を取得
        id_token_parts = token_data['id_token'].split('.')
        if len(id_token_parts) < 2:
            raise Exception("Invalid ID Token format.")
            
        # Base64URLデコード処理 (JWTのペイロード部分)
        payload_base64 = id_token_parts[1]
        
        # Base64URLを標準Base64に変換し、パディングを追加
        # Base64URLはパディング（=）を持たないため、手動で付加
        padding = '=' * (4 - len(payload_base64) % 4)
        payload_base64 = payload_base64 + padding
        
        # デコードしてJSONとしてパース
        id_token_payload = json.loads(base64.urlsafe_b64decode(payload_base64).decode('utf-8'))

        line_user_id = id_token_payload.get('sub') # 'sub'はLINE User ID

        if not line_user_id:
            raise Exception("LINE User ID ('sub') not found in ID Token.")
        
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        # 6. DBにLINE IDを紐付け
        cursor.execute('UPDATE users SET line_user_id = %s WHERE id = %s', (line_user_id, user_id))
        conn.commit()
        conn.close()
        
        flash("✅ LINE連携が完了しました！リマインダー通知が届きます。", 'success')
        
    except Exception as e:
        print("LINE連携エラー:", e)
        flash("LINE連携中にエラーが発生しました。設定（LINE Developers側）とコールバックURLを確認してください。", 'error')
        
    # 連携完了後、設定画面に戻す
    return redirect(url_for('setting'))


# --- その他のエンドポイント ---

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
    my_feedback = dict(my_recovery_data[0]) if my_recovery_data else None

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
    my_streak = 0
    if result['first_study'] and result['last_study']:
        # date型同士の引き算でtimedeltaが返るので.daysで日数を取得
        first_study = result['first_study']
        last_study = result['last_study']
        # 記録が1日しかない場合は0日ではなく1日としたい
        my_streak = (last_study - first_study).days + 1


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
    elif order_by == 'new':
        cursor.execute('''
            SELECT re.id, re.user_id, users.username, re.reason, re.improvement, re.created_at, re.likes
            FROM re
            JOIN users ON re.user_id = users.id
            WHERE re.is_shared = TRUE
            ORDER BY re.created_at DESC
            LIMIT %s OFFSET %s
        ''', (per_page, offset))
    # streakでの並べ替えはDBでは行わず、全件取得後Pythonで処理（パフォーマンス考慮）
    else: # order_by == 'streak' またはデフォルト以外の無効値
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

    if order_by != 'streak':
        recovery_data = [dict(row) for row in cursor.fetchall()]
        for row in recovery_data:
            row['streak'] = streak_map.get(row['user_id'], 0)

    # ページ数取得
    cursor.execute('SELECT COUNT(*) FROM re WHERE is_shared = TRUE')
    total_records = cursor.fetchone()[0]
    total_pages = (total_records + per_page - 1) // per_page

    # いいね済の投稿
    cursor.execute('SELECT re_id FROM re_likes WHERE user_id = %s', (user_id,))
    liked_ids = [row['re_id'] for row in cursor.fetchall()]
    conn.close()

    return render_template('resilience.html',
                           my_recovery_data=[dict(r) for r in my_recovery_data],
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
        reminder_time = request.form.get('reminder_time') or '18:00'

        # reminder_time はフォームから文字列 "HH:MM" で来る
        
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

            # セッションのユーザー情報を更新
            session_user = session.get('user', {})
            session_user.update({
                'goal': goal,
                'weekly_target': int(weekly_target),
                'small_action': small_action,
                'anchor': anchor,
                'failure_days': int(failure_days),
                'reminder_time': str(reminder_time)
            })

            # session['user'] は @app.before_request で常にクリーンアップされる
            session['user'] = session_user

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

        if setting and setting['reminder_time'] and isinstance(setting['reminder_time'], time):
            setting = dict(setting)
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
    first_study_date = None
    latest_study_date = None
    if records:
        first_study_date = records[0]['study_date']
        latest_study_date = records[-1]['study_date']

    # 最終回復実行日を取得
    cursor.execute('''
        SELECT MAX(created_at::date) AS latest_recovery_date
        FROM re
        WHERE user_id = %s
    ''', (user_id,))
    result = cursor.fetchone()
    latest_recovery_date = result['latest_recovery_date']

    # 継続日数の計算
    continuity_days = 0
    if first_study_date and latest_study_date:
        start_date = first_study_date
        if latest_recovery_date and latest_recovery_date > first_study_date:
            # 最新の回復日（re.created_at）が最初の学習日より後なら、そこから継続日数をカウント
            # ただし、回復プログラム実行日より新しい学習記録がある場合に限る
            if latest_recovery_date < latest_study_date:
                start_date = latest_recovery_date

        # 最終学習日から開始日までの日数
        continuity_days = (latest_study_date - start_date).days + 1


    # カテゴリ名取得
    cursor.execute('''
        SELECT id, category_name FROM study_categories WHERE user_id = %s
    ''', (user_id,))
    category_map = {row['id']: row['category_name'] for row in cursor.fetchall()}

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
            
            # カテゴリ名の重複チェック
            cursor.execute('SELECT 1 FROM study_categories WHERE user_id = %s AND LOWER(category_name) = LOWER(%s)', (user_id, new_category))
            if cursor.fetchone():
                return jsonify({'success': False, 'message': 'そのカテゴリは既に存在します。'}), 400
            
            # 挿入
            cursor.execute('INSERT INTO study_categories (user_id, category_name) VALUES (%s, %s) RETURNING id', (user_id, new_category))
            new_id = cursor.fetchone()['id']
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'id': new_id}), 200

        # 学習記録フォームからのPOST
        study_date = request.form.get('study_date')
        study_time = request.form.get('study_time')
        category_id = request.form.get('category_id')
        memo = request.form.get('memo')

        if not study_time or not study_time.isdigit() or int(study_time) <= 0:
            flash("学習時間は1分以上の数字で入力してください。")
            conn.close()
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


# pandasはDocker環境でインストールされていることを前提とする
import pandas as pd

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

    
    df = pd.DataFrame(records, columns=['study_date', 'study_time'])
    df['study_date'] = pd.to_datetime(df['study_date'])
    # 時刻情報を取り除き、比較用に日付のみを使用
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    max_time = int(df['study_time'].max()) if not df.empty else 60

    def generate_date_range(start, end):
        return pd.date_range(start=start, end=end)

    weekly_data, monthly_data, yearly_data = [], [], []
    weekly_avg = monthly_avg = yearly_avg = 0

    if period == 'week':
        # 終了日は「今日」からoffset週前の日曜日。開始日はそこから6日前。
        # today は datetime.datetime なので timedelta で計算
        end_date = today - timedelta(days=7 * offset)
        start_date = end_date - timedelta(days=6)
        
        full_range = generate_date_range(start_date, end_date, freq='D')
        target_df = df[(df['study_date'] >= start_date) & (df['study_date'] <= end_date)]
        
        # 欠損日を0で埋める
        filled_df = pd.DataFrame({'study_date': full_range})
        merged = pd.merge(filled_df, target_df, on='study_date', how='left').fillna(0)
        
        weekly_data = merged.to_dict(orient='records')
        weekly_avg = round(merged['study_time'].mean(), 1)

    if period == 'month':
        # 終了日は「今日」からoffsetヶ月前の今日。開始日はそこから29日前。
        end_date = today - timedelta(days=30 * offset)
        start_date = end_date - timedelta(days=29) # 30日間
        
        full_range = generate_date_range(start_date, end_date, freq='D')
        target_df = df[(df['study_date'] >= start_date) & (df['study_date'] <= end_date)]
        
        filled_df = pd.DataFrame({'study_date': full_range})
        merged = pd.merge(filled_df, target_df, on='study_date', how='left').fillna(0)
        monthly_data = merged.to_dict(orient='records')
        monthly_avg = round(merged['study_time'].mean(), 1)

    if period == 'year':
        # 過去12ヶ月の月別平均
        
        # study_dateを'YYYY-MM'の期間（Period）に変換
        df['year_month'] = df['study_date'].dt.to_period('M').astype(str)
        
        # 過去12ヶ月の期間を生成
        recent_months = pd.period_range(end=today, periods=12, freq='M').astype(str)
        month_df = pd.DataFrame({'year_month': recent_months})
        
        # 月ごとの平均学習時間を計算
        grouped = df.groupby('year_month')['study_time'].sum().reset_index()
        
        # 過去12ヶ月の期間と平均値をマージし、記録がない月は0で埋める
        merged = pd.merge(month_df, grouped, on='year_month', how='left').fillna(0)
        
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

# --- 1. AIによる初期提案生成 (質問回答直後のステップ用) ---
def generate_recovery_proposal(q1, q2, q3, goal, small_action):
    """3つの質問回答に基づいた初期分析と具体的な再開案の提案を行う"""
    prompt = f"""
あなたは習慣化コーチです。学習習慣が途切れたユーザーに対し、診断結果に基づいた分析と提案を行ってください。

【ユーザーの現在の設定】
・学習目的: {goal}
・現在の「小さな行動」: {small_action}

【診断結果】
1. 状況のパターン: {q1}
2. アンカー（きっかけ）の状態: {q2}
3. 行動の負担感（ハードル）: {q3}

上記に基づき、以下の2点を回答してください。
1. 分析：習慣化理論（Atomic Habits）に基づき、なぜ今回つまずいたのかを100文字程度で優しく解説。
2. 具体的な提案：明日から再開するための「さらにハードルを下げた行動」や「環境の整え方」を2〜3案、具体的に提示してください。

条件：
専門用語（アンカー、トリガー、Atomic Habitsなど）は使わず、ユーザーの自尊心を高める励ましのトーンで回答してください。
"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    response = model.generate_content(prompt)
    return response.text.strip()

# --- 2. ユーザーの入力に対する最終アドバイス生成 ---
def generate_feedback_advice(reason, improvement):
    """ユーザーが自分で考えた原因と対策に対して、さらに背中を押すアドバイスを生成"""
    prompt = f"""
原因：{reason}
対策：{improvement}

こちらはユーザーがAIの提案を受けて、自分なりに導き出した原因と対策です。
この内容を肯定しつつ、実行可能性を高めるための短いアドバイスを添えてください。
最後には「応援しています！」といったメッセージで締めてください。
"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    response = model.generate_content(prompt)
    return response.text.strip()

# --- 3. 詳細な学習記録分析 (レポート保存用) ---
def generate_gemini_analysis(user_id, goal, weekly_target):
    """過去の全学習記録を分析して、深い洞察を提供する（レポート画面で使用）"""
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor(cursor_factory=DictCursor)

    cursor.execute('''
        SELECT study_date, study_time, category_id
        FROM record
        WHERE user_id = %s
        ORDER BY study_date
    ''', (user_id,))
    records = cursor.fetchall()
    
    cursor.execute('SELECT id, category_name FROM study_categories WHERE user_id = %s', (user_id,))
    category_map = {row['id']: row['category_name'] for row in cursor.fetchall()}

    days = set()
    total_time = 0
    record_text_list = []
    
    for r in records:
        days.add(r['study_date'])
        total_time += r['study_time']
        category_name = category_map.get(r['category_id'], '未分類')
        record_text_list.append(f"{r['study_date'].strftime('%m/%d')} {category_name}")

    actual_days = len(days)
    avg_time = round(total_time / actual_days) if actual_days else 0

    # 継続日数計算
    first_study_date = records[0]['study_date'] if records else None
    latest_study_date = records[-1]['study_date'] if records else None
    cursor.execute('SELECT MAX(created_at::date) FROM re WHERE user_id = %s', (user_id,))
    latest_recovery_date = cursor.fetchone()[0]
    
    continuity_days = 0
    if first_study_date and latest_study_date:
        start_date = first_study_date
        if latest_recovery_date and latest_recovery_date > first_study_date:
            if latest_recovery_date < latest_study_date:
                start_date = latest_recovery_date
        continuity_days = (latest_study_date - start_date).days + 1

    record_text = ', '.join(record_text_list[-10:])
    conn.close()
    
    if not record_text:
        return "学習記録が不足しているため、深い分析はスキップされました。"

    prompt = f"""
学習記録をもとに分析してください。
・学習目的: {goal}
・週の目標日数: {weekly_target}日
・過去の学習日数: {actual_days}日
・直近の学習内容: {record_text}
・平均学習時間: {avg_time}分
・継続日数: {continuity_days}日

これらを踏まえ、ユーザーの学習傾向と、今後挫折しないための長期的なアドバイスを提示してください。
"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    response = model.generate_content(prompt)
    return response.text.strip()

# --- recovery ルート ---
@app.route('/recovery', methods=['GET', 'POST'])
def recovery():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = session['user']
    user_id = user['id']
    goal = user.get('goal') or "学習目標"
    small_action = user.get('small_action') or "小さな行動"
    weekly_target = user.get('weekly_target', 3)

    if request.method == 'POST':
        data = request.get_json()
        mode = data.get('mode') # 'propose' (AI提案) または 'save' (最終保存)

        # モード1: 3つの質問回答後のAI提案生成
        if mode == 'propose':
            try:
                # 学習分析（suggested_result）もここで生成して返すように修正
                # これにより、表示された内容をそのまま保存に回せるようにする
                proposal = generate_recovery_proposal(
                    data.get('q1'), data.get('q2'), data.get('q3'), 
                    goal, small_action
                )
                analysis = generate_gemini_analysis(user_id, goal, weekly_target)
                return jsonify({'proposal': proposal, 'analysis': analysis})
            except Exception as e:
                print(f"Proposal Error: {e}")
                return jsonify({'error': 'AI提案の生成に失敗しました'}), 500

        # モード2: ユーザーの入力内容をDBに保存
        elif mode == 'save':
            reason = data.get('reason', '').strip()
            improvement = data.get('improvement', '').strip()
            # フロントエンドで表示されていた分析結果を受け取る（内容の不一致を防ぐ）
            detailed_analysis = data.get('analysis', '').strip()
            is_shared = bool(data.get('is_shared', False))

            if not reason or not improvement:
                return jsonify({'error': '原因と対策を入力してください。'}), 400

            try:
                # 診断結果をまとめる
                full_reason_for_db = (
                    f"【診断】状況:{data.get('q1')}, アンカー:{data.get('q2')}, 負担感:{data.get('q3')}\n"
                    f"【ユーザー記述】{reason}"
                )
                
                # 最終アドバイス生成
                advice = generate_feedback_advice(reason, improvement)
                
                # 分析結果が送られてきていない場合のみ再生成（基本は送られてくる想定）
                if not detailed_analysis or "失敗しました" in detailed_analysis:
                    detailed_analysis = generate_gemini_analysis(user_id, goal, weekly_target)

                # データベースへの保存
                conn = psycopg2.connect(**db_config)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO re (user_id, reason, improvement, ai_feedback, re_analysis, is_shared, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ''', (user_id, full_reason_for_db, improvement, advice, detailed_analysis, is_shared))
                conn.commit()
                conn.close()

                return jsonify({'success': True, 'advice': advice})
            except Exception as e:
                print(f"Final Save Error: {e}")
                return jsonify({'error': '保存中にエラーが発生しました'}), 500

    # GETリクエスト時
    return render_template('re.html')


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
    else:
        # すでにいいね済みの場合、何もせずlike数を返す
        pass


    # 最新のlike数を取得して返す
    cursor.execute('SELECT likes FROM re WHERE id = %s', (re_id,))
    updated_likes = cursor.fetchone()[0]
    conn.close()

    return jsonify({'success': True, 'likes': updated_likes})

# LINE BotのWebhookは Bot のみで使用するため、LINEログインとは分離
@app.route("/line/webhook", methods=["POST"])
def line_webhook():
    body = request.get_json()
    events = body.get("events", [])
    # 実際には、署名検証やメッセージ応答ロジックが必要
    print(f"Received LINE Webhook: {body}")

    return jsonify({"status": "ok"})

# --- 回復レポート表示（履歴対応） ---
@app.route('/recovery/report')
def view_recovery_report():
    if 'user' not in session:
        return redirect(url_for('login'))

    search_username = request.args.get('username')
    selected_re_id = request.args.get('re_id') # 特定の履歴ID
    report = None
    history = []

    if search_username:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor(cursor_factory=DictCursor)
        
        # 1. まず、そのユーザーの全履歴リストを取得
        cursor.execute('''
            SELECT r.id, r.created_at
            FROM re r
            JOIN users u ON r.user_id = u.id
            WHERE u.username = %s
            ORDER BY r.created_at DESC
        ''', (search_username,))
        history = cursor.fetchall()

        # 2. 表示する特定のレポート詳細を取得
        if history:
            if selected_re_id:
                # IDが指定されている場合はそのIDの記録
                cursor.execute('''
                    SELECT 
                        u.username, u.goal, u.small_action,
                        r.id, r.created_at, r.reason, r.improvement, r.ai_feedback, r.re_analysis
                    FROM re r
                    JOIN users u ON r.user_id = u.id
                    WHERE r.id = %s AND u.username = %s
                ''', (selected_re_id, search_username))
            else:
                # 指定がない場合は最新（historyの最初）の記録
                cursor.execute('''
                    SELECT 
                        u.username, u.goal, u.small_action,
                        r.id, r.created_at, r.reason, r.improvement, r.ai_feedback, r.re_analysis
                    FROM re r
                    JOIN users u ON r.user_id = u.id
                    WHERE r.id = %s
                ''', (history[0]['id'],))
            
            result = cursor.fetchone()
            if result:
                report = dict(result)
        
        conn.close()

    return render_template('recovery_report.html', 
                           report=report, 
                           history=history,
                           search_username=search_username)



# ログアウト
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()  # データベース初期化
    app.run(debug=True)
