#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: omi
# @Date:   2014-08-24 21:51:57
'''
网易云音乐 Api
'''

import re
import os
import json
import time
import hashlib
import base64

from Crypto.Cipher import AES
from cookielib import LWPCookieJar
from bs4 import BeautifulSoup
import requests

from storage import Storage
from utils import notify
import logger

# 歌曲榜单地址
top_list_all = {
    # 列表编号，榜单名，榜单ID
    0: ['内地', 5],
    1: ['新歌', 27],
    2: ['港台', 6],
    3: ['欧美', 3],
}

default_timeout = 10

log = logger.getLogger(__name__)

modulus = ('00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7'
           'b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280'
           '104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932'
           '575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b'
           '3ece0462db0a22b8e7')
nonce = '0CoJUm6Qyw8W8jud'
pubKey = '010001'


# 歌曲加密算法, 基于https://github.com/yanunon/NeteaseCloudMusic脚本实现
def encrypted_id(id):
    magic = bytearray('3go8&$8*3*3h0k(2)2')
    song_id = bytearray(id)
    magic_len = len(magic)
    for i, sid in enumerate(song_id):
        song_id[i] = sid ^ magic[i % magic_len]
    m = hashlib.md5(song_id)
    result = m.digest().encode('base64')[:-1]
    result = result.replace('/', '_')
    result = result.replace('+', '-')
    return result


# 登录加密算法, 基于https://github.com/stkevintan/nw_musicbox脚本实现
def encrypted_request(text):
    text = json.dumps(text)
    secKey = createSecretKey(16)
    encText = aesEncrypt(aesEncrypt(text, nonce), secKey)
    encSecKey = rsaEncrypt(secKey, pubKey, modulus)
    data = {'params': encText, 'encSecKey': encSecKey}
    return data


def aesEncrypt(text, secKey):
    pad = 16 - len(text) % 16
    text = text + pad * chr(pad)
    encryptor = AES.new(secKey, 2, '0102030405060708')
    ciphertext = encryptor.encrypt(text)
    ciphertext = base64.b64encode(ciphertext)
    return ciphertext


def rsaEncrypt(text, pubKey, modulus):
    text = text[::-1]
    rs = pow(int(text.encode('hex'), 16), int(pubKey, 16), int(modulus, 16))
    return format(rs, 'x').zfill(256)


def createSecretKey(size):
    return (''.join(map(lambda xx: (hex(ord(xx))[2:]), os.urandom(size))))[0:16]


# list去重
def uniq(arr):
    arr2 = list(set(arr))
    arr2.sort(key=arr.index)
    return arr2


# 获取高音质mp3 url
def get_stream_url(song_id):
    br_to_quality = {128000: 'MD 128k', 320000: 'HD 320k'}
    url = NetEase().get_stream_url(song_id)
    quality = ''  # TODO:quantity
    return url


class NetEase(object):
    def __init__(self):
        self.header = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip,deflate,sdch',
            'Accept-Language': 'zh-CN,zh;q=0.8,gl;q=0.6,zh-TW;q=0.4',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Host': 'i.y.qq.com',
            'Referer': 'http://y.qq.com',
            'User-Agent':
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/33.0.1750.152 Safari/537.36'
            # NOQA
        }
        self.cookies = {'appver': '1.5.2'}
        self.playlist_class_dict = {}
        self.session = requests.Session()
        self.storage = Storage()
        self.session.cookies = LWPCookieJar(self.storage.cookie_path)
        try:
            self.session.cookies.load()
            self.file = file(self.storage.cookie_path, 'r')
            cookie = self.file.read()
            self.file.close()
            pattern = re.compile(r'\d{4}-\d{2}-\d{2}')
            str = pattern.findall(cookie)
            if str:
                if str[0] < time.strftime('%Y-%m-%d',
                                          time.localtime(time.time())):
                    self.storage.database['user'] = {
                        'username': '',
                        'password': '',
                        'user_id': '',
                        'nickname': '',
                    }
                    self.storage.save()
                    os.remove(self.storage.cookie_path)
        except IOError as e:
            log.error(e)
            self.session.cookies.save()

    def return_toplists(self):
        return [l[0] for l in top_list_all.values()]

    def httpRequest(self,
                    method,
                    action,
                    query=None,
                    urlencoded=None,
                    callback=None,
                    timeout=None):
        connection = json.loads(self.rawHttpRequest(
            method, action, query, urlencoded, callback, timeout))
        return connection

    def rawHttpRequest(self,
                       method,
                       action,
                       query=None,
                       urlencoded=None,
                       callback=None,
                       timeout=None):
        if method == 'GET':
            url = action if query is None else action + '?' + query
            connection = self.session.get(url,
                                          headers=self.header,
                                          timeout=default_timeout)

        elif method == 'POST':
            connection = self.session.post(action,
                                           data=query,
                                           headers=self.header,
                                           timeout=default_timeout)

        elif method == 'Login_POST':
            connection = self.session.post(action,
                                           data=query,
                                           headers=self.header,
                                           timeout=default_timeout)
            self.session.cookies.save()

        connection.encoding = 'UTF-8'
        return connection.text

    # 登录
    def login(self, username, password):
        pattern = re.compile(r'^0\d{2,3}\d{7,8}$|^1[34578]\d{9}$')
        if (pattern.match(username)):
            return self.phone_login(username, password)
        action = 'https://music.163.com/weapi/login/'
        text = {
            'username': username,
            'password': password,
            'rememberLogin': 'true'
        }
        data = encrypted_request(text)
        try:
            return self.httpRequest('Login_POST', action, data)
        except requests.exceptions.RequestException as e:
            log.error(e)
            return {'code': 501}

    # 手机登录
    def phone_login(self, username, password):
        action = 'https://music.163.com/weapi/login/cellphone'
        text = {
            'phone': username,
            'password': password,
            'rememberLogin': 'true'
        }
        data = encrypted_request(text)
        try:
            return self.httpRequest('Login_POST', action, data)
        except requests.exceptions.RequestException as e:
            log.error(e)
            return {'code': 501}

    # 每日签到
    def daily_signin(self, type):
        action = 'http://music.163.com/weapi/point/dailyTask'
        text = {'type': type}
        data = encrypted_request(text)
        try:
            return self.httpRequest('POST', action, data)
        except requests.exceptions.RequestException as e:
            log.error(e)
            return -1

    # 用户歌单
    def user_playlist(self, uid, offset=0, limit=100):
        action = 'http://music.163.com/api/user/playlist/?offset={}&limit={}&uid={}'.format(  # NOQA
                                                                                              offset, limit, uid)
        try:
            data = self.httpRequest('GET', action)
            return data['playlist']
        except (requests.exceptions.RequestException, KeyError) as e:
            log.error(e)
            return -1

    # 每日推荐歌单
    def recommend_playlist(self):
        try:
            action = 'http://music.163.com/weapi/v1/discovery/recommend/songs?csrf_token='  # NOQA
            self.session.cookies.load()
            csrf = ''
            for cookie in self.session.cookies:
                if cookie.name == '__csrf':
                    csrf = cookie.value
            if csrf == '':
                return False
            action += csrf
            req = {'offset': 0, 'total': True, 'limit': 20, 'csrf_token': csrf}
            page = self.session.post(action,
                                     data=encrypted_request(req),
                                     headers=self.header,
                                     timeout=default_timeout)
            results = json.loads(page.text)['recommend']
            song_ids = []
            for result in results:
                song_ids.append(result['id'])
            data = map(self.song_info, song_ids)
            return [data[i][0] for i in range(len(data))]
        except (requests.exceptions.RequestException, ValueError) as e:
            log.error(e)
            return False

    # 私人FM
    def personal_fm(self):
        action = 'http://music.163.com/api/radio/get'
        try:
            data = self.httpRequest('GET', action)
            return data['data']
        except requests.exceptions.RequestException as e:
            log.error(e)
            return -1

    # like
    def fm_like(self, songid, like=True, time=25, alg='itembased'):
        action = 'http://music.163.com/api/radio/like?alg={}&trackId={}&like={}&time={}'.format(  # NOQA
                                                                                                  alg, songid,
                                                                                                  'true' if like else 'false',
                                                                                                  time)

        try:
            data = self.httpRequest('GET', action)
            if data['code'] == 200:
                return data
            else:
                return -1
        except requests.exceptions.RequestException as e:
            log.error(e)
            return -1

    # FM trash
    def fm_trash(self, songid, time=25, alg='RT'):
        action = 'http://music.163.com/api/radio/trash/add?alg={}&songId={}&time={}'.format(  # NOQA
                                                                                              alg, songid, time)
        try:
            data = self.httpRequest('GET', action)
            if data['code'] == 200:
                return data
            else:
                return -1
        except requests.exceptions.RequestException as e:
            log.error(e)
            return -1

    def search(self, key, stype='songs', offset=0, total='true', limit=60):
        import urllib
        action = "http://i.y.qq.com/s.plcloud/fcgi-bin/smartbox_new.fcg?utf8=1&is_xml=0&{key_query}" \
                 "&g_tk=1371149499&format=jsonp&inCharset=GB2312&outCharset=utf-8&notice=0&platform=yqq" \
                 "&jsonpCallback=MusicJsonCallBack&needNewCode=0".format(key_query=urllib.urlencode({'key': key}))
        resp = self.session.get(action)
        json_body = resp.text.split('MusicJsonCallBack(')[1].strip(')')
        data = json.loads(json_body)['data']
        if stype == 'artists':
            stype = 'singers'
        stype = stype[:-1]  # 比如songs=>转成song
        result = data.get(stype, [])
        if not result:
            return []
        return result['itemlist']

    # 新碟上架 http://music.163.com/#/discover/album/
    def new_albums(self, offset=0, limit=50):
        action = 'http://music.163.com/api/album/new?area=ALL&offset={}&total=true&limit={}'.format(  # NOQA
                                                                                                      offset, limit)
        try:
            data = self.httpRequest('GET', action)
            return data['albums']
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    # 歌单（网友精选碟） hot||new http://music.163.com/#/discover/playlist/
    def top_playlists(self, category='全部', order='hot', offset=0, limit=50):
        action = 'http://music.163.com/api/playlist/list?cat={}&order={}&offset={}&total={}&limit={}'.format(  # NOQA
                                                                                                               category,
                                                                                                               order,
                                                                                                               offset,
                                                                                                               'true' if offset else 'false',
                                                                                                               limit)  # NOQA
        try:
            data = self.httpRequest('GET', action)
            return data['playlists']
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    # 分类歌单
    def playlist_classes(self):
        action = 'http://music.163.com/discover/playlist/'
        try:
            data = self.rawHttpRequest('GET', action)
            return data
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    # 分类歌单中某一个分类的详情
    def playlist_class_detail(self):
        pass

    # 歌单详情
    def playlist_detail(self, playlist_id):
        action = 'http://music.163.com/api/playlist/detail?id={}'.format(
            playlist_id)
        try:
            data = self.httpRequest('GET', action)
            return data['result']['tracks']
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    # 热门歌手 http://music.163.com/#/discover/artist/
    def top_artists(self, offset=0, limit=100):
        action = 'http://music.163.com/api/artist/top?offset={}&total=false&limit={}'.format(  # NOQA
                                                                                               offset, limit)
        try:
            data = self.httpRequest('GET', action)
            return data['artists']
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    # 热门单曲 http://music.163.com/discover/toplist?id=
    def top_songlist(self, idx=0, offset=0, limit=100):
        # action = 'http://music.163.com' + top_list_all[idx][1]
        top_id = top_list_all[idx][1]
        action = "http://i.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg?tpl=20&page=detail&date=2016_27" \
                 "&type=top&topid={top_id}&g_tk=1371149499&format=json" \
                 "&inCharset=GB2312&outCharset=utf-8" \
                 "&notice=0&platform=yqq&jsonpCallback=toplistSongList1468337817052&needNewCode=0".format(top_id=top_id)
        try:
            headers = self.header
            headers[
                'Referer'] = "http://i.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg?page=detail&type=top&topid={top_id}&format=html&tpl=20".format(
                top_id=top_id)
            connection = requests.get(action,
                                      headers=headers,
                                      timeout=default_timeout)
            connection.encoding = 'UTF-8'
            json_body = connection.text.split('toplistSongList1468337817052(')[1].strip(')')
            songs = json.loads(json_body)['songlist']
            # TODO:slice
            return [self.song_info(song['data']['songmid'], song['data']) for song in songs]  # 已经包含song_info一样的歌曲信息
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    # 歌手单曲
    def artists(self, singermid):
        # TODO:pagination
        action = "http://i.y.qq.com/v8/fcg-bin/fcg_v8_singer_track_cp.fcg?g_tk=938407465&format=jsonp&inCharset=GB2312&outCharset=utf-8&notice=0" \
                 "&platform=yqq&jsonpCallback=MusicJsonCallback&needNewCode=0" \
                 "&singermid={singermid}&order=listen&begin=0&num=15&songstatus=1".format(singermid=singermid)
        try:
            headers = self.session.headers
            headers[
                'Referer'] = 'http://i.y.qq.com/v8/fcg-bin/fcg_v8_singer_detail_cp.fcg?tpl=20&singermid={singermid}'.format(
                singermid=singermid)
            resp = self.session.request('GET', action, headers=headers)
            json_body = resp.text.split('(', 1)[1].strip(')')
            data = json.loads(json_body)
            if data['code'] != 0:
                log.error("Response invalid:" + action)
                return []
            data = data['data']['list']
            songs = [song['musicData'] for song in data]
            return songs
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    # album id --> song id set
    def album(self, album_id):
        action = 'http://music.163.com/api/album/{}'.format(album_id)
        try:
            data = self.httpRequest('GET', action)
            return data['album']['songs']
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    def get_stream_url(self, song_id):
        """
        获取歌曲音频流地址
        :param song_id:
        :return:
        """
        mtime = self.storage.last_modified_time()
        ctime = time.time()
        vkey = ''
        if ctime - mtime < 3600:
            # vkey在一定有效时间能通用
            vkey = self.storage.database['vkey']
        if not vkey:
            config_url = "http://base.music.qq.com/fcgi-bin/fcg_musicexpress.fcg?json=3&guid=5746725496&g_tk=178887276" \
                         "&format=jsonp&inCharset=GB2312&outCharset=GB2312&notice=0&platform=yqq" \
                         "&jsonpCallback=jsonCallback&needNewCode=0"
            resp = self.session.get(config_url)
            json_body = resp.content.split('(')[1].strip(');')
            config = json.loads(json_body)
            if not config or config['code'] != 0:
                notify('无法获取歌曲播放地址')
            vkey = config['key']
            # save the latest vkey
            self.storage.database['vkey'] = vkey
            self.storage.save()
        # TODO:C200?
        song_url = "http://ws.stream.qqmusic.qq.com/{song_id}.m4a?vkey={vkey}&guid=5746725496&fromtag=30".format(
            song_id="C200" + song_id, vkey=vkey)
        return song_url

    def song_info(self, song_id, song_data=None):
        """

        :param song_id:
        :param song_data: 获取列表信息时有可能已经返回歌曲信息了，直接使用
        :return:
        """
        if not song_data:
            url = "http://i.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg?songmid={song_id}&tpl=yqq_song_detail&play=0".format(
                song_id=song_id)
            resp = self.session.request('GET', url)
            song_data = re.findall(r"g_SongData\s?=\s?(\{.+\})", resp.content)
            song_data = song_data[0]
            song_data = json.loads(song_data)
        if not song_data:
            # print("Cannot retrieve song info")  # TODO:empty info
            # print("Resp is " + resp.content)
            return {}

        song_data['singername'] = song_data['singer'][0]['name']  # TODO:multiple singers?
        return song_data

    def song_lyric(self, song_id):
        """
        获取歌词信息
        :param song_id:
        :return:
        """
        action = "http://i.y.qq.com/lyric/fcgi-bin/fcg_query_lyric.fcg?pcachetime={time}&songmid={song_id}&g_tk=938407465" \
                 "&format=jsonp&inCharset=GB2312&outCharset=utf-8" \
                 "&notice=0&platform=yqq&jsonpCallback=MusicJsonCallback&needNewCode=0".format(song_id=song_id,
                                                                                               time=str(int(
                                                                                                   time.time())) + "000")
        try:
            headers = self.header
            resp = self.session.request('GET', action, headers=headers)
            json_body = resp.content.split('(')[1].strip(")")
            result = json.loads(json_body)
            if not result or result['retcode'] != 0:
                lyric_info = '未找到歌词'
            else:
                lyric_info = base64.b64decode(result['lyric'])
            return lyric_info
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    def song_tlyric(self, music_id):
        return []  # TODO:lyric translation
        action = 'http://music.163.com/api/song/lyric?os=osx&id={}&lv=-1&kv=-1&tv=-1'.format(  # NOQA
                                                                                               music_id)
        try:
            data = self.httpRequest('GET', action)
            if 'tlyric' in data and data['tlyric']['lyric'] is not None:
                lyric_info = data['tlyric']['lyric'][1:]
            else:
                lyric_info = '未找到歌词翻译'
            return lyric_info
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    # 今日最热（0）, 本周最热（10），历史最热（20），最新节目（30）
    def djchannels(self, stype=0, offset=0, limit=50):
        action = 'http://music.163.com/discover/djradio?type={}&offset={}&limit={}'.format(  # NOQA
                                                                                             stype, offset, limit)
        try:
            connection = requests.get(action,
                                      headers=self.header,
                                      timeout=default_timeout)
            connection.encoding = 'UTF-8'
            channelids = re.findall(r'/program\?id=(\d+)', connection.text)
            channelids = uniq(channelids)
            return self.channel_detail(channelids)
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    # DJchannel ( id, channel_name ) ids --> song urls ( details )
    # 将 channels 整理为 songs 类型
    def channel_detail(self, channelids, offset=0):
        channels = []
        for i in range(0, len(channelids)):
            action = 'http://music.163.com/api/dj/program/detail?id={}'.format(
                channelids[i])
            try:
                data = self.httpRequest('GET', action)
                channel = self.dig_info(data['program']['mainSong'],
                                        'channels')
                channels.append(channel)
            except requests.exceptions.RequestException as e:
                log.error(e)
                continue

        return channels

    # 获取版本
    def get_version(self):
        action = 'https://pypi.python.org/pypi?:action=doap&name=NetEase-MusicBox'  # NOQA
        try:
            data = requests.get(action)
            return data.content
        except requests.exceptions.RequestException as e:
            log.error(e)
            return []

    def dig_info(self, data, dig_type):
        temp = []
        if dig_type == 'songs' or dig_type == 'fmsongs':
            for i in range(0, len(data)):
                song_info = data[i]
                song_info['quality'] = ''  # TODO:quality
                song_info['singername'] = song_info['singer'][0]['name']
                temp.append(song_info)

        elif dig_type == 'artists':
            artists = []
            for artist_basic_info in data:
                artist_info = {
                    'artist_id': artist_basic_info['mid'],
                    'artists_name': artist_basic_info['singer'],
                    'alias': ''  # TODO:alias
                }
                artists.append(artist_info)

            return artists

        elif dig_type == 'albums':
            for i in range(0, len(data)):
                albums_info = {
                    'album_id': data[i]['id'],
                    'albums_name': data[i]['name'],
                    'artists_name': data[i]['singername']['name']
                }
                temp.append(albums_info)

        elif dig_type == 'top_playlists':
            for i in range(0, len(data)):
                playlists_info = {
                    'playlist_id': data[i]['id'],
                    'playlists_name': data[i]['name'],
                    'creator_name': data[i]['creator']['nickname']
                }
                temp.append(playlists_info)

        elif dig_type == 'channels':
            url = get_stream_url(data)
            quality = ''
            channel_info = {
                'songmid': data['id'],
                'songname': data['name'],
                'artist': data['artists'][0]['name'],
                'albumname': '主播电台',
                'mp3_url': url,
                'quality': quality
            }
            temp = channel_info

        elif dig_type == 'playlist_classes':
            soup = BeautifulSoup(data, 'lxml')
            dls = soup.select('dl.f-cb')
            for dl in dls:
                title = dl.dt.text
                sub = [item.text for item in dl.select('a')]
                temp.append(title)
                self.playlist_class_dict[title] = sub

        elif dig_type == 'playlist_class_detail':
            log.debug(data)
            temp = self.playlist_class_dict[data]

        return temp


if __name__ == '__main__':
    ne = NetEase()
    # print geturl_new_api(ne.songs_detail([27902910])[0])  # MD 128k, fallback
    # print ne.get_stream_url('00309Hdu17kB1T')
    # print ne.top_songlist(0)
    # print(ne.search('陈奕迅', 'singers'))
    print(ne.artists('003Nz2So3XXYek'))
    # print ne.song_info('00309Hdu17kB1T')['singername']
    # print ne.song_lyric('00309Hdu17kB1T')
    # print ne.dig_info(ne.top_songlist(0),'songs')
    # print ne.songs_detail([405079776])[0]['mp3Url']  # old api
    # print requests.get(ne.songs_detail([405079776])[0][
    #     'mp3Url']).status_code  # 404
