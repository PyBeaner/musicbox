#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: omi
# @Date:   2014-08-24 21:51:57
'''
网易云音乐 Ui
'''
import hashlib
import re
import curses

from api import NetEase
from scrollstring import scrollstring, truelen
from storage import Storage
from config import Config
from utils import notify
import logger
import terminalsize

log = logger.getLogger(__name__)

try:
    import dbus

    dbus_activity = True
except ImportError:
    dbus_activity = False
    log.warn('dbus module not installed.')
    log.warn('Osdlyrics Not Available.')


def escape_quote(text):
    return text.replace('\'', '\\\'').replace('\'', '\'\'')


class Ui(object):
    def __init__(self):
        self.screen = curses.initscr()
        self.screen.timeout(100)  # the screen refresh every 100ms
        # charactor break buffer
        curses.cbreak()
        self.screen.keypad(1)
        self.netease = NetEase()

        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        # term resize handling
        size = terminalsize.get_terminal_size()
        self.x = max(size[0], 10)
        self.y = max(size[1], 25)
        self.startcol = int(float(self.x) / 5)
        self.indented_startcol = max(self.startcol - 3, 0)
        self.update_space()
        self.lyric = ''
        self.now_lyric = ''
        self.tlyric = ''
        self.storage = Storage()
        self.config = Config()
        self.newversion = False

    def notify(self, summary, song, album, artist):
        if summary != 'disable':
            body = '%s\nin %s by %s' % (song, album, artist)
            content = escape_quote(summary + ': ' + body)
            notify(content)

    def build_playinfo(self,
                       song_name,
                       artist,
                       album_name,
                       quality,
                       start,
                       pause=False):
        curses.noecho()
        # refresh top 2 line
        self.screen.move(1, 1)
        self.screen.clrtoeol()
        self.screen.move(2, 1)
        self.screen.clrtoeol()
        if pause:
            self.screen.addstr(1, self.indented_startcol,
                               '_ _ z Z Z ' + quality, curses.color_pair(3))
        else:
            self.screen.addstr(1, self.indented_startcol,
                               '♫  ♪ ♫  ♪ ' + quality, curses.color_pair(3))

        self.screen.addstr(
            1, min(self.indented_startcol + 18, self.x - 1),
            song_name + self.space + artist + '  < ' + album_name + ' >',
            curses.color_pair(4))

        self.screen.refresh()

    def build_process_bar(self, now_playing, total_length, playing_flag,
                          pause_flag, playing_mode):
        """
        进度条
        :param now_playing: 秒
        :param total_length: 秒
        :param playing_flag:
        :param pause_flag:
        :param playing_mode:
        :return:
        """
        if (self.storage.database['player_info']['idx'] >=
                len(self.storage.database['player_info']['player_list'])):
            return
        curses.noecho()
        self.screen.move(3, 1)
        self.screen.clrtoeol()
        self.screen.move(4, 1)
        self.screen.clrtoeol()
        if not playing_flag:
            return
        if total_length <= 0:
            total_length = 1
        if now_playing > total_length or now_playing <= 0:
            now_playing = 0
        # 进度条 ［>>>>    ］
        process = '['
        arrow_count = int(now_playing / (total_length * 1.0) * 33)
        process += '>' * arrow_count
        if pause_flag:
            process += '='
        process += (33 - arrow_count) * ' '
        process += '] '
        now_minute = int(now_playing / 60)
        if now_minute > 9:
            now_minute = str(now_minute)
        else:
            now_minute = '0' + str(now_minute)
        now_second = int(now_playing - int(now_playing / 60) * 60)
        if now_second > 9:
            now_second = str(now_second)
        else:
            now_second = '0' + str(now_second)
        total_minute = int(total_length / 60)
        if total_minute > 9:
            total_minute = str(total_minute)
        else:
            total_minute = '0' + str(total_minute)
        total_second = int(total_length - int(total_length / 60) * 60)
        if total_second > 9:
            total_second = str(total_second)
        else:
            total_second = '0' + str(total_second)
        process += '(' + now_minute + ':' + now_second + '/' + total_minute + ':' + total_second + ')'  # NOQA
        if playing_mode == 0:
            process = '顺序播放 ' + process
        elif playing_mode == 1:
            process = '顺序循环 ' + process
        elif playing_mode == 2:
            process = '单曲循环 ' + process
        elif playing_mode == 3:
            process = '随机播放 ' + process
        elif playing_mode == 4:
            process = '随机循环 ' + process
        else:
            pass
        self.screen.addstr(3, self.startcol - 2, process, curses.color_pair(1))
        song = self.storage.database['songs'][
            self.storage.database['player_info']['player_list'][
                self.storage.database['player_info']['idx']]]
        if 'lyric' not in song.keys() or len(song['lyric']) <= 0:
            self.now_lyric = '暂无歌词 ~>_<~ \n'
            if dbus_activity and self.config.get_item('osdlyrics'):
                self.now_playing = song['songname'] + ' - ' + song['singername'] + '\n'

        else:
            key = now_minute + ':' + now_second
            for line in song['lyric']:
                if key in line:
                    if 'tlyric' not in song.keys() or len(song['tlyric']) <= 0:
                        self.now_lyric = line
                    else:
                        self.now_lyric = line
                        for tline in song['tlyric']:
                            if key in tline and self.config.get_item(
                                    'translation'):
                                self.now_lyric = tline + ' || ' + self.now_lyric  # NOQA
        self.now_lyric = re.sub('\[.*?\]', '', self.now_lyric)
        if dbus_activity and self.config.get_item('osdlyrics'):
            try:
                bus = dbus.SessionBus().get_object('org.musicbox.Bus', '/')
                if self.now_lyric == '暂无歌词 ~>_<~ \n':
                    bus.refresh_lyrics(self.now_playing,
                                       dbus_interface='local.musicbox.Lyrics')
                else:
                    bus.refresh_lyrics(self.now_lyric,
                                       dbus_interface='local.musicbox.Lyrics')
            except Exception as e:
                log.error(e)
                pass
        self.screen.addstr(4, self.startcol - 2, str(self.now_lyric),
                           curses.color_pair(3))
        self.screen.refresh()

    def build_loading(self):
        self.screen.addstr(7, self.startcol, '享受高品质音乐，loading...',
                           curses.color_pair(1))
        self.screen.refresh()

    # start is the timestamp of this function being called
    def build_menu(self, datatype, title, datalist, offset, index, step,
                   start):
        # keep playing info in line 1
        curses.noecho()
        self.screen.move(5, 1)
        self.screen.clrtobot()
        self.screen.addstr(5, self.startcol, title, curses.color_pair(1))

        if len(datalist) == 0:
            self.screen.addstr(8, self.startcol, '这里什么都没有 -，-')

        else:
            if datatype == 'main':
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(i - offset + 9,
                                           self.indented_startcol,
                                           '-> ' + str(i) + '. ' + datalist[i],
                                           curses.color_pair(2))
                    else:
                        self.screen.addstr(i - offset + 9, self.startcol,
                                           str(i) + '. ' + datalist[i])

            elif datatype == 'songs' or datatype == 'fmsongs':
                iter_range = min(len(datalist), offset + step)
                for i in range(offset, iter_range):
                    # this item is focus
                    if i == index:
                        self.screen.addstr(i - offset + 8, 0,
                                           ' ' * self.startcol)
                        lead = '-> ' + str(i) + '. '
                        self.screen.addstr(i - offset + 8,
                                           self.indented_startcol, lead,
                                           curses.color_pair(2))
                        name = '{}{}{}  < {} >'.format(
                            datalist[i]['songname'], self.space,
                            datalist[i]['singername'], datalist[i]['albumname'])

                        # the length decides whether to scoll
                        if truelen(name) < self.x - self.startcol - 1:
                            self.screen.addstr(
                                i - offset + 8,
                                self.indented_startcol + len(lead), name,
                                curses.color_pair(2))
                        else:
                            name = scrollstring(name + '  ', start)
                            self.screen.addstr(
                                i - offset + 8,
                                self.indented_startcol + len(lead), str(name),
                                curses.color_pair(2))
                    else:
                        self.screen.addstr(i - offset + 8, 0,
                                           ' ' * self.startcol)
                        self.screen.addstr(
                            i - offset + 8, self.startcol,
                            '{}. {}{}{}  < {} >'.format(
                                i, datalist[i]['songname'], self.space,
                                datalist[i]['singername'],  # TODO:get singer name
                                datalist[i]['albumname'])[:int(self.x * 2)])

                self.screen.addstr(iter_range - offset + 8, 0, ' ' * self.x)

            elif datatype == 'artists':
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(
                            i - offset + 9, self.indented_startcol,
                            '-> ' + str(i) + '. ' + datalist[i]['artists_name']
                            + self.space + str(datalist[i]['alias']),
                            curses.color_pair(2))
                    else:
                        self.screen.addstr(
                            i - offset + 9, self.startcol,
                            str(i) + '. ' + datalist[i]['artists_name'] +
                            self.space + datalist[i][
                                'alias'])

            elif datatype == 'albums':
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(
                            i - offset + 9, self.indented_startcol,
                            '-> ' + str(i) + '. ' + datalist[i]['albums_name']
                            + self.space + datalist[i][
                                'artists_name'], curses.color_pair(2))
                    else:
                        self.screen.addstr(
                            i - offset + 9, self.startcol,
                            str(i) + '. ' + datalist[i]['albums_name'] +
                            self.space + datalist[i][
                                'artists_name'])

            elif datatype == 'playlists':
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(
                            i - offset + 9, self.indented_startcol,
                            '-> ' + str(i) + '. ' + datalist[i]['title'],
                            curses.color_pair(2))
                    else:
                        self.screen.addstr(
                            i - offset + 9, self.startcol,
                            str(i) + '. ' + datalist[i]['title'])

            elif datatype == 'top_playlists':
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(
                            i - offset + 9, self.indented_startcol, '-> ' +
                            str(i) + '. ' + datalist[i]['playlists_name'] +
                            self.space + datalist[i]['creator_name'],
                            curses.color_pair(2))
                    else:
                        self.screen.addstr(
                            i - offset + 9, self.startcol,
                            str(i) + '. ' + datalist[i]['playlists_name'] +
                            self.space + datalist[i][
                                'creator_name'])

            elif datatype == 'toplists':
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(i - offset + 9,
                                           self.indented_startcol,
                                           '-> ' + str(i) + '. ' + datalist[i],
                                           curses.color_pair(2))
                    else:
                        self.screen.addstr(i - offset + 9, self.startcol,
                                           str(i) + '. ' + datalist[i])

            elif datatype in ('playlist_classes', 'playlist_class_detail'):
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(i - offset + 9,
                                           self.indented_startcol,
                                           '-> ' + str(i) + '. ' + datalist[i],
                                           curses.color_pair(2))
                    else:
                        self.screen.addstr(i - offset + 9, self.startcol,
                                           str(i) + '. ' + datalist[i])

            elif datatype == 'djchannels':
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(
                            i - offset + 8, self.indented_startcol,
                            '-> ' + str(i) + '. ' + datalist[i]['songname'],
                            curses.color_pair(2))
                    else:
                        self.screen.addstr(
                            i - offset + 8, self.startcol,
                            str(i) + '. ' + datalist[i]['songname'])

            elif datatype == 'search':
                self.screen.move(6, 1)
                self.screen.clrtobot()
                self.screen.timeout(-1)
                self.screen.addstr(8, self.startcol, '选择搜索类型:',
                                   curses.color_pair(1))
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(
                            i - offset + 10, self.indented_startcol,
                            '-> ' + str(i) + '.' + datalist[i - 1],
                            curses.color_pair(2))
                    else:
                        self.screen.addstr(i - offset + 10, self.startcol,
                                           str(i) + '.' + datalist[i - 1])
                self.screen.timeout(100)

            elif datatype == 'help':
                for i in range(offset, min(len(datalist), offset + step)):
                    if i == index:
                        self.screen.addstr(
                            i - offset + 9, self.indented_startcol,
                            '-> {}. \'{}{}   {}'.format(
                                i, (datalist[i][0].upper() + '\'').ljust(11),
                                datalist[i][1], datalist[i][2]),
                            curses.color_pair(2))
                    else:
                        self.screen.addstr(
                            i - offset + 9, self.startcol,
                            '{}. \'{}{}   {}'.format(
                                i, (datalist[i][0].upper() + '\'').ljust(11),
                                datalist[i][1], datalist[i][2]))

                self.screen.addstr(
                    20, 6, 'NetEase-MusicBox 基于Python，所有版权音乐来源于网易，本地不做任何保存')
                self.screen.addstr(21, 10,
                                   '按 [G] 到 Github 了解更多信息，帮助改进，或者Star表示支持~~')
                self.screen.addstr(22, self.startcol,
                                   'Build with love to music by omi')

        self.screen.refresh()

    def build_search(self, stype):
        self.screen.timeout(-1)
        netease = self.netease
        if stype == 'songs':
            prompt = '搜索歌曲：'
        elif stype == 'artists':
            prompt = '搜索歌手：'
        elif stype == 'albums':
            prompt = '搜索专辑：'
        elif stype == 'search_playlist':  # TODO:mv
            prompt = '搜索精选集：'
        else:
            return []

        search_key = self.get_param(prompt)
        if search_key == '/return':
            return []

        data = netease.search(search_key, stype=stype)
        if stype == 'songs':
            data = [netease.song_info(song['mid']) for song in data]
            return data
        return netease.dig_info(data, stype)

    def build_login(self):
        self.build_login_bar()
        local_account = self.get_account()
        local_password = hashlib.md5(self.get_password()).hexdigest()
        login_info = self.netease.login(local_account, local_password)
        account = [local_account, local_password]
        if login_info['code'] != 200:
            x = self.build_login_error()
            if x == ord('1'):
                return self.build_login()
            else:
                return -1
        else:
            return [login_info, account]

    def build_login_bar(self):
        curses.noecho()
        self.screen.move(4, 1)
        self.screen.clrtobot()
        self.screen.addstr(5, self.startcol, '请输入登录信息(支持手机登陆)',
                           curses.color_pair(1))
        self.screen.addstr(8, self.startcol, '账号:', curses.color_pair(1))
        self.screen.addstr(9, self.startcol, '密码:', curses.color_pair(1))
        self.screen.move(8, 24)
        self.screen.refresh()

    def build_login_error(self):
        self.screen.move(4, 1)
        self.screen.timeout(-1)  # disable the screen timeout
        self.screen.clrtobot()
        self.screen.addstr(8, self.startcol, '艾玛，登录信息好像不对呢 (O_O)#',
                           curses.color_pair(1))
        self.screen.addstr(10, self.startcol, '[1] 再试一次')
        self.screen.addstr(11, self.startcol, '[2] 稍后再试')
        self.screen.addstr(14, self.startcol, '请键入对应数字:', curses.color_pair(2))
        self.screen.refresh()
        x = self.screen.getch()
        self.screen.timeout(100)  # restore the screen timeout
        return x

    def get_account(self):
        self.screen.timeout(-1)  # disable the screen timeout
        curses.echo()
        account = self.screen.getstr(8, self.startcol + 6, 60)
        self.screen.timeout(100)  # restore the screen timeout
        return account

    def get_password(self):
        self.screen.timeout(-1)  # disable the screen timeout
        curses.noecho()
        password = self.screen.getstr(9, self.startcol + 6, 60)
        self.screen.timeout(100)  # restore the screen timeout
        return password

    def get_param(self, prompt_string):
        # keep playing info in line 1
        curses.echo()
        self.screen.move(4, 1)
        self.screen.clrtobot()
        self.screen.addstr(5, self.startcol, prompt_string,
                           curses.color_pair(1))
        self.screen.refresh()
        info = self.screen.getstr(10, self.startcol, 60)
        if info == '':
            return '/return'
        elif info.strip() is '':
            return self.get_param(prompt_string)
        else:
            return info

    def update_size(self):
        # get terminal size
        size = terminalsize.get_terminal_size()
        self.x = max(size[0], 10)
        self.y = max(size[1], 25)

        # update intendations
        curses.resizeterm(self.y, self.x)
        self.startcol = int(float(self.x) / 5)
        self.indented_startcol = max(self.startcol - 3, 0)
        self.update_space()
        self.screen.clear()
        self.screen.refresh()

    def update_space(self):
        if self.x > 140:
            self.space = '   -   '
        elif self.x > 80:
            self.space = '  -  '
        else:
            self.space = ' - '
        self.screen.refresh()
