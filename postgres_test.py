# import postgres driver
import psycopg2

# connect to the database
conn = psycopg2.connect(database="postgres", user="postgres", password="postgres", host="localhost", port="25434")

# create a cursor
cur = conn.cursor()

# execute a statement
cur.execute("SELECT * FROM users")

# fetch the results
rows = cur.fetchall()

# print the results
print(rows)