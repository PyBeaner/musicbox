#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: omi
# @Date:   2014-07-15 15:48:27
# @Last Modified by:   omi
# @Last Modified time: 2015-01-30 18:05:08
'''
网易云音乐 Player
'''
# Let's make some noise

import subprocess
import threading
import time
import os
import random

from ui import Ui
from storage import Storage
from api import NetEase
from cache import Cache
from config import Config
import logger
from api import get_stream_url

log = logger.getLogger(__name__)


class Player(object):
    def __init__(self):
        self.config = Config()
        self.ui = Ui()
        self.popen_handler = None
        # flag stop, prevent thread start
        self.playing_flag = False
        self.pause_flag = False
        self.process_length = 0
        self.process_location = 0
        self.storage = Storage()
        self.info = self.storage.database['player_info']
        self.songs = self.storage.database['songs']
        self.playing_id = -1
        self.cache = Cache()
        self.notifier = self.config.get_item('notifier')
        self.mpg123_parameters = self.config.get_item('mpg123_parameters')
        self.end_callback = None
        self.playing_song_changed_callback = None

    def popen_recall(self, onExit, popenArgs):
        '''
        Runs the given args in subprocess.Popen, and then calls the function
        onExit when the subprocess completes.
        onExit is a callable object, and popenArgs is a lists/tuple of args
        that would give to subprocess.Popen.
        '''

        def runInThread(onExit, popenArgs):
            # para = ['mpg123', '-R']
            # para[1:1] = self.mpg123_parameters
            if 'cache' in popenArgs:
                stream_url = popenArgs['cache']
            elif 'mp3_url' in popenArgs:
                stream_url = popenArgs['mp3_url']
            else:
                stream_url = ''

            if not stream_url:
                self.next_idx()
                onExit()
                return

            fifo = '/tmp/mplayer.fifo'
            if not os.path.exists(fifo):
                os.mkfifo(fifo)
            # see Slave Mode:https://www.mplayerhq.hu/DOCS/tech/slave.txt
            para = ['mplayer', '-slave', '-input', 'file=' + fifo, stream_url]
            self.popen_handler = subprocess.Popen(para,
                                                  stdin=subprocess.PIPE,
                                                  stdout=subprocess.PIPE,
                                                  stderr=subprocess.PIPE)
            self.popen_handler.stdin.write('V ' + str(self.info[
                                                          'playing_volume']) + '\n')
            self.popen_handler.stdin.write(stream_url)

            # get seconds of the song
            size = popenArgs['size320']
            self.process_length = self._size_to_seconds(size, 320)

            while True:
                if self.playing_flag is False:
                    break

                self.popen_handler.stdin.write('get_percent_pos\n')
                stdout = self.popen_handler.stdout.readline()
                # TODO:why it takes two seconds to update the position
                # 当前进度
                if 'ANS_PERCENT_POSITION' in stdout:
                    percentage = stdout.split('=')[1].strip()
                    # 当前歌曲播放完了
                    if percentage == '100':
                        self.popen_handler.stdin.write('quit\n')
                        self.popen_handler.kill()
                        break
                    self.process_location = self.process_length * int(percentage) / 100

                # if stdout == '@P 0\n':
                #     self.popen_handler.stdin.write('Q\n')
                #     self.popen_handler.kill()
                #     break

            if self.playing_flag:
                self.next_idx()
                onExit()

        def getLyric():
            if 'lyric' not in self.songs[str(self.playing_id)].keys():
                self.songs[str(self.playing_id)]['lyric'] = []
            if len(self.songs[str(self.playing_id)]['lyric']) > 0:
                return
            netease = NetEase()
            lyric = netease.song_lyric(self.playing_id)
            if lyric == [] or lyric == '未找到歌词':
                return
            lyric = lyric.split('\n')
            lyric = [line for line in lyric if not line.endswith(']')]
            self.songs[str(self.playing_id)]['lyric'] = lyric
            return

        def gettLyric():
            if 'tlyric' not in self.songs[str(self.playing_id)].keys():
                self.songs[str(self.playing_id)]['tlyric'] = []
            if len(self.songs[str(self.playing_id)]['tlyric']) > 0:
                return
            netease = NetEase()
            tlyric = netease.song_tlyric(self.playing_id)
            if tlyric == [] or tlyric == '未找到歌词翻译':
                return
            tlyric = tlyric.split('\n')
            self.songs[str(self.playing_id)]['tlyric'] = tlyric
            return

        def cacheSong(song_id, song_name, artist, song_url):
            def cacheExit(song_id, path):
                self.songs[str(song_id)]['cache'] = path

            self.cache.add(song_id, song_name, artist, song_url, cacheExit)
            self.cache.start_download()

        # 是否缓存过？
        if 'cache' not in popenArgs.keys() or not os.path.isfile(popenArgs['cache']):
            cache_thread = threading.Thread(
                target=cacheSong,
                args=(popenArgs['songmid'], popenArgs['songname'], popenArgs[
                    'singername'], popenArgs['mp3_url']))
            cache_thread.start()

        thread = threading.Thread(target=runInThread,
                                  args=(onExit, popenArgs))
        thread.start()
        lyric_download_thread = threading.Thread(target=getLyric, args=())
        lyric_download_thread.start()
        tlyric_download_thread = threading.Thread(target=gettLyric, args=())
        tlyric_download_thread.start()
        # returns immediately after the thread starts
        return thread

    def get_playing_id(self):
        return self.playing_id

    def recall(self):
        if self.info['idx'] >= len(self.info[
                                       'player_list']) and self.end_callback is not None:
            log.debug('Callback')
            self.end_callback()
        if self.info['idx'] < 0 or self.info['idx'] >= len(self.info[
                                                               'player_list']):
            self.info['idx'] = 0
            self.stop()
            return
        self.playing_flag = True
        self.pause_flag = False
        item = self.songs[self.info['player_list'][self.info['idx']]]
        self.ui.build_playinfo(item['songname'], item['singername'],
                               item['albumname'], item['quality'],
                               time.time())
        if self.notifier:
            self.ui.notify('Now playing', item['songname'],
                           item['albumname'], item['singername'])
        self.playing_id = item['songmid']
        if 'mp3_url' not in item:  # 获取音频流地址比较慢，所以没有预先全部获取
            item['mp3_url'] = get_stream_url(item['songmid'])
        self.popen_recall(self.recall, item)

    def generate_shuffle_playing_list(self):
        del self.info['playing_list'][:]
        for i in range(0, len(self.info['player_list'])):
            self.info['playing_list'].append(i)
        random.shuffle(self.info['playing_list'])
        self.info['ridx'] = 0

    def new_player_list(self, type, title, datalist, offset):
        self.info['player_list_type'] = type
        self.info['player_list_title'] = title
        self.info['idx'] = offset
        del self.info['player_list'][:]
        del self.info['playing_list'][:]
        self.info['ridx'] = 0
        for song in datalist:
            self.info['player_list'].append(str(song['songmid']))
            if str(song['songmid']) not in self.songs.keys():
                self.songs[str(song['songmid'])] = song
            else:
                database_song = self.songs[str(song['songmid'])]
                if (database_song['songname'] != song['songname'] or
                            database_song['quality'] != song['quality']):
                    self.songs[str(song['songmid'])] = song

    def append_songs(self, datalist):
        for song in datalist:
            self.info['player_list'].append(str(song['songmid']))
            if str(song['songmid']) not in self.songs.keys():
                self.songs[str(song['songmid'])] = song
            else:
                database_song = self.songs[str(song['songmid'])]
                cond = any([database_song[k] != song[k]
                            for k in ('songname', 'quality', 'mp3_url')])
                if cond:
                    if 'cache' in self.songs[str(song['songmid'])].keys():
                        song['cache'] = self.songs[str(song['songmid'])][
                            'cache']
                    self.songs[str(song['songmid'])] = song
        if len(datalist) > 0 and self.info['playing_mode'] == 3 or self.info[
            'playing_mode'] == 4:
            self.generate_shuffle_playing_list()

    def play_and_pause(self, idx):
        # if same playlists && idx --> same song :: pause/resume it
        if self.info['idx'] == idx:
            if self.pause_flag:
                self.resume()
            else:
                self.pause()
        else:
            self.info['idx'] = idx

            # if it's playing
            if self.playing_flag:
                self.switch()

            # start new play
            else:
                self.recall()

    # play another
    def switch(self):
        self.stop()
        # wait process be killed
        time.sleep(0.1)
        self.recall()

    def stop(self):
        if self.playing_flag and self.popen_handler:
            self.playing_flag = False
            self.popen_handler.stdin.write('quit\n')  # Quit
            try:
                self.popen_handler.kill()
            except OSError as e:
                log.error(e)
                return

    def pause(self):
        if not self.playing_flag and not self.popen_handler:
            return
        self.pause_flag = True
        self.popen_handler.stdin.write('pause\n')

        item = self.songs[self.info['player_list'][self.info['idx']]]
        self.ui.build_playinfo(item['songname'],
                               item['singername'],
                               item['albumname'],
                               item['quality'],
                               time.time(),
                               pause=True)

    def resume(self):
        self.pause_flag = False
        self.popen_handler.stdin.write('pause\n')  # same as 'pause'

        item = self.songs[self.info['player_list'][self.info['idx']]]
        self.ui.build_playinfo(item['songname'], item['singername'],
                               item['albumname'], item['quality'],
                               time.time())
        self.playing_id = item['songmid']

    def _swap_song(self):
        plist = self.info['playing_list']
        now_songs = plist.index(self.info['idx'])
        plist[0], plist[now_songs] = plist[now_songs], plist[0]

    def _is_idx_valid(self):
        return 0 <= self.info['idx'] < len(self.info['player_list'])

    def _inc_idx(self):
        if self.info['idx'] < len(self.info['player_list']):
            self.info['idx'] += 1

    def _dec_idx(self):
        if self.info['idx'] > 0:
            self.info['idx'] -= 1

    def _need_to_shuffle(self):
        playing_list = self.info['playing_list']
        ridx = self.info['ridx']
        idx = self.info['idx']
        if ridx >= len(playing_list) or playing_list[ridx] != idx:
            return True
        else:
            return False

    def next_idx(self):
        if not self._is_idx_valid():
            self.stop()
            return
        playlist_len = len(self.info['player_list'])
        playinglist_len = len(self.info['playing_list'])

        # Playing mode. 0 is ordered. 1 is ordered loop.
        # 2 is single song loop. 3 is single random. 4 is random loop
        if self.info['playing_mode'] == 0:
            self._inc_idx()
        elif self.info['playing_mode'] == 1:
            self.info['idx'] = (self.info['idx'] + 1) % playlist_len
        elif self.info['playing_mode'] == 2:
            self.info['idx'] = self.info['idx']
        elif self.info['playing_mode'] == 3 or self.info['playing_mode'] == 4:
            if self._need_to_shuffle():
                self.generate_shuffle_playing_list()
                playinglist_len = len(self.info['playing_list'])
                # When you regenerate playing list
                # you should keep previous song same.
                try:
                    self._swap_song()
                except Exception as e:
                    log.error(e)
            self.info['ridx'] += 1
            # Out of border
            if self.info['playing_mode'] == 4:
                self.info['ridx'] %= playinglist_len
            if self.info['ridx'] >= playinglist_len:
                self.info['idx'] = playlist_len
            else:
                self.info['idx'] = self.info['playing_list'][self.info['ridx']]
        else:
            self.info['idx'] += 1
        if self.playing_song_changed_callback is not None:
            self.playing_song_changed_callback()

    def next(self):
        self.stop()
        time.sleep(0.01)
        self.next_idx()
        self.recall()

    def prev_idx(self):
        if not self._is_idx_valid():
            self.stop()
            return
        playlist_len = len(self.info['player_list'])
        playinglist_len = len(self.info['playing_list'])
        # Playing mode. 0 is ordered. 1 is orderde loop.
        # 2 is single song loop. 3 is single random. 4 is random loop
        if self.info['playing_mode'] == 0:
            self._dec_idx()
        elif self.info['playing_mode'] == 1:
            self.info['idx'] = (self.info['idx'] - 1) % playlist_len
        elif self.info['playing_mode'] == 2:
            self.info['idx'] = self.info['idx']
        elif self.info['playing_mode'] == 3 or self.info['playing_mode'] == 4:
            if self._need_to_shuffle():
                self.generate_shuffle_playing_list()
                playinglist_len = len(self.info['playing_list'])
            self.info['ridx'] -= 1
            if self.info['ridx'] < 0:
                if self.info['playing_mode'] == 3:
                    self.info['ridx'] = 0
                else:
                    self.info['ridx'] %= playinglist_len
            self.info['idx'] = self.info['playing_list'][self.info['ridx']]
        else:
            self.info['idx'] -= 1
        if self.playing_song_changed_callback is not None:
            self.playing_song_changed_callback()

    def prev(self):
        self.stop()
        time.sleep(0.01)
        self.prev_idx()
        self.recall()

    def shuffle(self):
        self.stop()
        time.sleep(0.01)
        self.info['playing_mode'] = 3
        self.generate_shuffle_playing_list()
        self.info['idx'] = self.info['playing_list'][self.info['ridx']]
        self.recall()

    def volume_up(self):
        self.info['playing_volume'] = self.info['playing_volume'] + 7
        if (self.info['playing_volume'] > 100):
            self.info['playing_volume'] = 100
        if not self.playing_flag:
            return
        self.popen_handler.stdin.write('V ' + str(self.info[
                                                      'playing_volume']) + '\n')

    def volume_down(self):
        self.info['playing_volume'] = self.info['playing_volume'] - 7
        if (self.info['playing_volume'] < 0):
            self.info['playing_volume'] = 0
        if not self.playing_flag:
            return

        self.popen_handler.stdin.write('V ' + str(self.info[
                                                      'playing_volume']) + '\n')

    def update_size(self):
        try:
            self.ui.update_size()
            item = self.songs[self.info['player_list'][self.info['idx']]]
            if self.playing_flag:
                self.ui.build_playinfo(item['songname'], item['singername'],
                                       item['albumname'], item['quality'],
                                       time.time())
            if self.pause_flag:
                self.ui.build_playinfo(item['songname'],
                                       item['singername'],
                                       item['albumname'],
                                       item['quality'],
                                       time.time(),
                                       pause=True)
        except Exception as e:
            log.error(e)
            pass

    def cacheSong1time(self, song_id, song_name, artist, song_url):
        def cacheExit(song_id, path):
            self.songs[str(song_id)]['cache'] = path
            self.cache.enable = False

        self.cache.enable = True
        self.cache.add(song_id, song_name, artist, song_url, cacheExit)
        self.cache.start_download()

    @staticmethod
    def _size_to_seconds(size, rate):
        """
        http://www.audiomountain.com/tech/audio-file-size.html
        :param size: bytes of the file
        :param rate:
        :return:
        """
        table = {
            # rate=>KB per second
            320: 40,
            256: 32,
            128: 16
        }
        kb_per_second = table[rate]
        return size / kb_per_second / (10 ** 3)


if __name__ == '__main__':
    print(Player._size_to_seconds(11319601, 320))
