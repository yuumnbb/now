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

