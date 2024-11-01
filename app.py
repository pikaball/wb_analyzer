from flask import *
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
import base64
import time
from configparser import ConfigParser
import requests as rq
import json

app = Flask(__name__)

config = ConfigParser()
config.read("wb.conf")

connect_str = f"dbname={config['db']['dbname']} user={config['db']['user']} password={config['db']['password']} host={config['db']['host']} port={config['db']['port']}"

db_pool = ConnectionPool(
    connect_str, 
    min_size=1, 
    kwargs={"row_factory": dict_row}
)

def get_access_token():
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {"grant_type": "client_credentials", "client_id": config['ai']['API_KEY'], "client_secret": config['ai']['SECRET_KEY']}
    return str(rq.post(url, params=params).json().get("access_token"))

access_token = get_access_token()

def emotion(text):
    while True:  # 处理aps并发异常
        url = "https://aip.baidubce.com/rpc/2.0/nlp/v1/sentiment_classify?charset=UTF-8&access_token=" + access_token
        #headers = {'Content-Type': 'application/json', 'Connection': 'close'}  # headers=headers
        payload = json.dumps({
        "text": text
        })
        headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
        }
        rq.packages.urllib3.disable_warnings()
        try:
            res = rq.request("POST", url, headers=headers, data=payload)
            rc=res.status_code
            print(rc)
        except:
            print('发生错误，停五秒重试')
            time.sleep(5)
            continue
        if rc==200:
            print('正常请求中')
        else:
            print('遇到错误，重试')
            time.sleep(2)
            continue
        try:
            judge = res.text
            # print(judge)
        except:
            print('错误,正在重试，错误文本为：' + text)
            time.sleep(1)
            continue
        if judge == {'error_code': 18, 'error_msg': 'Open api qps request limit reached'}:
            print('并发量限制')
            time.sleep(1)
            continue
        elif 'error_msg' in judge:  # 如果出现意外的报错，就结束本次循环
            print('其他错误')
            time.sleep(1)
            continue
        else:
            break
    # print(judge)
    judge=eval(judge)#将字符串转换为字典
    #print(type(judge))
    # pm = judge["items"][0]["sentiment"]  # 情感分类
    # #print(pm)
    # # if pm == 0:
    # #     pm = '负向'
    # # elif pm == 1:
    # #     pm = '中性'
    # # else:
    # #     pm = '正向'
    # pp = judge["items"][0]["positive_prob"]  # 正向概率
    # pp = round(pp, 4)
    # #print(pp)
    # np = judge["items"][0]["negative_prob"]  # 负向概率
    # np = round(np, 4)
    # #print(np)
    return judge['items'][0]

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

def getemotion(mid):
    with db_pool.connection() as conn:
        emotion = conn.execute(
            "select * from emotion where mid = %s",
            [mid]
        ).fetchone()
    return emotion

def getdatas(topic):
    with db_pool.connection() as conn:
        datas = conn.execute(
            "select * from data where tid = %s",
            [topic]
        ).fetchall()
    # print(datas)
    datas = sorted(datas, key=lambda i: i['time'])
    for data in datas:
        data = translate_data(data)
        emo = getemotion(data['mid'])
        if emo == None:
            emo = emotion(data['content'])
            print(emo)
            with db_pool.connection() as conn:
                conn.execute(
                    "insert into emotion (mid, sentiment, positive_prob, negative_prob) values (%s, %s, %s, %s)",
                    [data['mid'], emo['sentiment'], emo['positive_prob'], emo['negative_prob']]
                )
        sen = emo['sentiment']
        if sen == 0:
            data['sentiment'] = '负向'
        elif sen == 1:
            data['sentiment'] = '中立'
        else:
            data['sentiment'] = '正向'
        data['positive'], data['negative'] = emo['positive_prob'], emo['negative_prob']
    return datas

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
    # print(getemotion(123))
    app.run(host='0.0.0.0', port='7000', debug=True)