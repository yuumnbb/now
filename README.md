# docker起動手順
- カレントディレクトリに移動
- ```sh docker.sh```

# postgresに接続 ローカル用
- ```psql -U postgres -h localhost -p 25434```

# ポスグレ接続heroku用
- ```heroku pg:psql```



# Heroku操作
## 参考文献

- [qiita](https://qiita.com/BanaoLihua/items/8a12b6f9c9f3289efcf5)
- [公式(python version)](https://devcenter.heroku.com/ja/articles/python-support)
- [Heroku cli install](https://devcenter.heroku.com/ja/articles/heroku-cli)

## heroku cli install
- ```​brew tap heroku/brew && brew install heroku```

## heroku cli login
- ```heroku login```

## runtime.txtを追加
- pythonのversionを定義する

## requirements.txtの用意
- ターミナルに```pip3 freeze > requirements.txt```を入力し、ライブラリを取得する

## Procfileを定義
- heroku上でpythonをどのように動かすか定義する
- ```web: gunicorn <実行ファイル名 ※拡張子は含まない>:app --log-file=-```
- 今回は実行ファイルがapp.py

## herokuにアプリを作成
- ```heroku create 任意の名前```

## herokuにpostgresqlを追加
- ```heroku addons:create 任意の名前:hobby-dev```

## ddl再起動
- dockerのある場所に移動
- cd ~/Desktop/Yusuke2/docker 
- コンテナ停止
- docker-compose down -v
- 再構築
- docker-compose up --build


## DB操作
$ docker exec -it postgresql bash

root@2bc82ca3ee4c:/# psql -U postgres -d postgres
psql (14.0 (Debian 14.0-1.pgdg110+1))
Type "help" for help.

postgres=# SELECT id, username, goal FROM users;
 id | username | goal 
----+----------+------
  1 | a        | a
  2 | aa       | 
  3 | aaa      | 
(3 rows)

postgres=# \q
root@2bc82ca3ee4c:/# exit

# PostgreSQLの接続設定
"""
db_config = {
    'host': '127.0.0.1',  # Dockerのホスト
    'database': 'postgres',  # デフォルトのデータベース名
    'user': 'postgres',
    'password': 'postgres',
    'port': 25434          # docker-composeで指定したポート
}
"""

"""
#Azure
db_config = {
    'host': 'myapp-postgres12345.postgres.database.azure.com',
    'port': 5432,
    'dbname': 'postgres',
    'user': 'postgres',
    'password': 'h8e267dR',
    'sslmode': 'require'
}
"""


Azure
psql




