# -*- coding: utf-8 -*-
import sys
sys.path.append('./vendor')

import os

from flask import Flask, request, abort

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    ButtonsTemplate, MessageTemplateAction, TemplateSendMessage, FollowEvent, ImageMessage, LocationMessage, MessageEvent, TextMessage, TextSendMessage, StickerSendMessage
)

import redis
import cloudinary
import cloudinary.uploader
import uuid
import json
import urllib.parse

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ.get('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('CHANNEL_SECRET'))

url = urllib.parse.urlparse(os.environ["REDIS_URL"])
pool = redis.ConnectionPool(host=url.hostname,
                            port=url.port,
                            db=url.path[1:],
                            password=url.password,
                            decode_responses=True)
r = redis.StrictRedis(connection_pool=pool)

@app.route("/", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']

    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

def notifyBlankField(event):
    required = ['lat', 'lon', 'url', 'comment', 'review']
    done = r.hkeys(event.source.user_id)

    blank = list(set(required) - set(done))

    if len(blank) == 0:
        r.hset(event.source.user_id, 'userid', event.source.user_id)
        r.rename(event.source.user_id, 'lm_' + uuid.uuid4().hex)

        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text='added landmark. You can egister another landmark or view all data by sending \'show\'')
            ]
        )
    else:
        str = 'saved. required: ' + ', '.join(blank)
        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text=str)
            ]
        )

@handler.add(FollowEvent)
def handle_follow(event):
    line_bot_api.reply_message(
        event.reply_token,
        [
            TextSendMessage(text="This BOT can store multiple landmark data that has location, image, comment and review. Send any of them."),
        ]
    )

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):

    lat = event.message.latitude
    lon = event.message.longitude

    r.hmset(event.source.user_id, {'lat': lat, 'lon': lon})

    notifyBlankField(event)

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):

    message_content = line_bot_api.get_message_content(event.message.id)
    dirname = 'tmp'
    fileName = uuid.uuid4().hex
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    with open("tmp/{fileName}.jpg", 'wb') as img:
        img.write(message_content.content)

    cloudinary.config(
        cloud_name = os.environ.get('CLOUDINARY_NAME'),
        api_key = os.environ.get('CLOUDINARY_KEY'),
        api_secret = os.environ.get('CLOUDINARY_SECRET')
    )
    result = cloudinary.uploader.upload("tmp/{fileName}.jpg")
    r.hset(event.source.user_id, 'url', result['secure_url'])

    notifyBlankField(event)

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if event.message.text == 'show':
        result = ''
        for h in r.keys('lm_*'):
            result += (json.dumps(r.hgetall(h)) + "\n")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))
        return

    if event.message.text in ['comment', 'review'] and r.hget(event.source.user_id, 'tmp') is not None:
        r.hset(event.source.user_id, event.message.text, r.hget(event.source.user_id, 'tmp'))
        r.hdel(event.source.user_id, 'tmp')
        notifyBlankField(event)
    else:
        r.hset(event.source.user_id, 'tmp', event.message.text)
        buttons_template = ButtonsTemplate(
            text="Which field to store '%s'?" % event.message.text, actions=[
                MessageTemplateAction(label='comment', text='comment'),
                MessageTemplateAction(label='review', text='review')
            ])
        template_message = TemplateSendMessage(
            alt_text='Alternative Text', template=buttons_template)
        line_bot_api.reply_message(event.reply_token, template_message)



if __name__ == "__main__":
    app.debug = True;
    app.run()
