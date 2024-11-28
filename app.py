from flask import *
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
import base64
import time
import os
from configparser import ConfigParser
import requests as rq
import json
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import jieba

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

with open('stopwords.txt', 'r', encoding='utf-8') as f:
    stopwords = f.read().split('\n')

def emotion(text):
    while True:  
        url = "https://aip.baidubce.com/rpc/2.0/nlp/v1/sentiment_classify?charset=UTF-8&access_token=" + access_token
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
        except:
            print('错误,正在重试，错误文本为：' + text)
            time.sleep(1)
            continue
        if judge == {'error_code': 18, 'error_msg': 'Open api qps request limit reached'}:
            print('并发量限制')
            time.sleep(1)
            continue
        elif 'error_msg' in judge: 
            print('其他错误')
            time.sleep(1)
            continue
        else:
            break
    judge=eval(judge)
    return judge['items'][0]

def get_topic_statistics(tid):
    with db_pool.connection() as conn:
        res = conn.execute(
            """
            SELECT 
                COUNT(data.mid) AS topics_count,
                SUM(CASE WHEN emotion.sentiment = 2 THEN 1 ELSE 0 END) AS pos_count,
                SUM(CASE WHEN emotion.sentiment = 1 THEN 1 ELSE 0 END) AS mid_count,
                SUM(CASE WHEN emotion.sentiment = 0 THEN 1 ELSE 0 END) AS neg_count
            FROM data
            LEFT JOIN emotion ON data.mid = emotion.mid
            WHERE data.tid = %s
            """, [tid]
        ).fetchone()
        return res

def content_filter(content):
    content = content.replace('\n', '')
    content = content.replace('\r', '')
    content = content.replace('\t', '')
    content = content.replace(' ', '')
    content = content.replace('，', ',')
    content = content.replace('。', '.')
    content = content.replace('！', '!')
    content = content.replace('？', '?')
    content = content.replace('“', '"')
    content = content.replace('”', '"')
    content = content.replace('‘', '\'')
    content = content.replace('’', '\'')
    content = content.replace('【', '[')
    content = content.replace('】', ']')
    content = content.replace('《', '<')
    content = content.replace('》', '>')
    content = content.replace('、', ',')
    content = content.replace('：', ':')
    content = content.replace('；', ';')
    content = content.replace('（', '(')
    content = content.replace('）', ')')
    content = content.replace('—', '-')
    content = content.replace('～', '~')
    content = content.replace('…', '...')
    content = content.replace('━', '-')
    content = content.replace('─', '-')
    content = content.replace('──', '-')
    return content

def generate_word_cloud(tid, max_word=20):
    wordcloud_path = f"static/wordclouds/{tid}.png"
    with db_pool.connection() as conn:
        result = conn.execute(
            "SELECT content FROM data WHERE tid = %s",
            [tid]
        ).fetchall()
    all_content = ""
    if len(result) == 0:
        return
    for row in result:
        content = base64.b64decode(row['content']).decode('utf-8')
        content = content_filter(content)
        cut_content = " ".join(jieba.lcut(content))
        all_content += cut_content + " "
    wordcloud = WordCloud(
        background_color="white",
        max_words=max_word, 
        width=800, 
        height=600, 
        random_state=1,
        font_path="/usr/share/fonts/Consolas-with-Yahei Nerd Font.ttf",
        stopwords=stopwords
    ).generate(all_content)
    wordcloud.to_file(wordcloud_path)

def filter_comments(comments):
        comment_decode = [base64.b64decode(comment['content'].encode()).decode() for comment in comments]
        return [comment for comment in comment_decode if '】' not in comment and len(comment) < 200]

def get_representation(tid):
    with db_pool.connection() as conn:
        pos_comments = conn.execute(
            """
            SELECT data.content 
            FROM data LEFT JOIN emotion ON data.mid=emotion.mid 
            WHERE data.tid=%s and emotion.sentiment=2 
            LIMIT 10
            """,
            [tid]
        ).fetchall()
        mid_comments = conn.execute(
            """
            SELECT data.content 
            FROM data LEFT JOIN emotion ON data.mid=emotion.mid 
            WHERE data.tid=%s and emotion.sentiment=1 
            LIMIT 10
            """,
            [tid]
        ).fetchall()
        neg_comments = conn.execute(
            """
            SELECT data.content 
            FROM data LEFT JOIN emotion ON data.mid=emotion.mid 
            WHERE data.tid=%s and emotion.sentiment=0 
            LIMIT 10
            """,
            [tid]
        ).fetchall()
    
    pos_comments = filter_comments(pos_comments)[:3]
    mid_comments = filter_comments(mid_comments)[:3]
    neg_comments = filter_comments(neg_comments)[:3]

    return {
        'positive': pos_comments,
        'neutral': mid_comments,
        'negative': neg_comments
    }

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
    topic = translate_topic(topic)
    statistics = get_topic_statistics(topic['tid'])
    representative_comments = get_representation(topic['tid'])
    topic['statistics'] = statistics
    topic['representative_comments'] = representative_comments
    return topic

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
    if not os.path.exists(f"static/wordclouds/{topic}.png"):
        generate_word_cloud(topic)
    return render_template("topic.html", topic = gettopic(topic), datas = getdatas(topic))

@app.route("/regenerate_wordcloud/<topic>")
def regenerate_wordcloud(topic):
    generate_word_cloud(topic)
    return redirect(url_for('topic', topic=topic))

if __name__=='__main__':
    # with db_pool.connection() as conn:
    #     print(conn.execute(
    #         "select * from data"
    #     ).fetchone()['time'].__class__)
    # print(getdatas(8))
    # print(getemotion(123))
    app.run(host='0.0.0.0', port='7000', debug=True)