from flask import Flask, render_template, request, redirect, url_for, session, flash
import bcrypt as bc
from datetime import datetime, timedelta
from flask_paginate import Pagination, get_page_parameter
import json

app = Flask(__name__)

app.secret_key = 'secret key'
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30) # 30分でセッションが切れる

@app.route('/mypage')
def mypage():
 return 

@app.route('/error')
def error():
  return "エラーが発生しました"

if __name__ == '__main__':
  app.run(debug=True)
