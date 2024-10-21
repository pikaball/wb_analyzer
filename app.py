from flask import *
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
import base64
import time
from configparser import ConfigParser

app = Flask(__name__)

config = ConfigParser()
config.read("db.conf")

connect_str = f"dbname={config['db']['dbname']} user={config['db']['user']} password={config['db']['password']} host={config['db']['host']} port={config['db']['port']}"

db_pool = ConnectionPool(
    connect_str, 
    min_size=1, 
    kwargs={"row_factory": dict_row}
)

def translate_topic(topic):
    topic['content'] = base64.b64decode(topic['content']).decode()
    return topic

def translate_data(data):
    data['content'] = base64.b64decode(data['content']).decode()
    data['time'] = time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(data['time']))
    return data

def gettopics():
    with db_pool.connection() as conn:
        topics = conn.execute(
            "select * from topic"
        ).fetchall()
    topics = list(map(translate_topic, topics))
    return sorted(topics, key=lambda i: i['tid'])

def gettopic(topic):
    with db_pool.connection() as conn:
        topic = conn.execute(
            "select * from topic where tid = %s",
            [topic]
        ).fetchone()
    return translate_topic(topic)

def getdatas(topic):
    with db_pool.connection() as conn:
        datas = conn.execute(
            "select * from data where tid = %s",
            [topic]
        ).fetchall()
    # print(datas)
    datas = sorted(datas, key=lambda i: i['time'])
    return list(map(translate_data, datas))

@app.route("/")
def index():
    with db_pool.connection() as conn:
        topic_sum = conn.execute(
            "select count(*) from topic"
        ).fetchone()['count']
        data_sum = conn.execute(
            "select count(*) from data"
        ).fetchone()['count']
    return render_template("index.html", topics=gettopics(), topic_sum=topic_sum, data_sum=data_sum)

@app.route("/topic/<topic>")
def topic(topic):
    return render_template("topic.html", topic = gettopic(topic), datas = getdatas(topic))

if __name__=='__main__':
    # with db_pool.connection() as conn:
    #     print(conn.execute(
    #         "select * from data"
    #     ).fetchone()['time'].__class__)
    # print(getdatas(8))

    app.run(host='0.0.0.0', port='7000', debug=True)