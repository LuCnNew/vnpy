# encoding: utf-8

from __future__ import print_function
try:
    from urllib.parse import urlparse
    from urllib.parse import urlencode
except:
    from urlparse import urlparse
    from urllib import urlencode

import urllib3
import hashlib
import requests
from queue import Queue, Empty
from multiprocessing.dummy import Pool
import hmac

import json
import websocket
import time

Trading_Macro_v2 = 'https://api.cointiger.pro/exchange/trading/api/v2'
Trading_Macro = 'https://api.cointiger.pro/exchange/trading/api'
Market_Macro = 'https://api.cointiger.pro/exchange/trading/api/market'
Market_List = 'https://www.cointiger.pro/exchange/api/public/market/detail'
Wss_Url = 'wss://api.cointiger.pro/exchange-market/ws'

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

########################################################################
class CointigerRestApi(object):
    """"""
    #----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self._api_key = ''
        self._secret = ''

        self.active = False         # API工作状态
        self.reqID = 0              # 请求编号
        self.queue = Queue()        # 请求队列
        self.pool = None            # 线程池
        self.sessionDict = {}       # 连接池

    #----------------------------------------------------------------------
    def init(self, apiKey, secretKey):
        """初始化"""
        self._api_key = str(apiKey)
        self._secret = str(secretKey)

    #----------------------------------------------------------------------
    def start(self, n=10):
        """"""
        if self.active:
            return

        self.active = True
        self.pool = Pool(n)
        self.pool.map_async(self.run, range(n))

    #----------------------------------------------------------------------
    def close(self):
        """退出"""
        self.active = False

        if self.pool:
            self.pool.close()
            self.pool.join()

    #----------------------------------------------------------------------
    def processReq(self, req, i):
        """处理请求"""
        # 读取方法和参数
        method, path, params, callback, reqID = req
        url = Trading_Macro + path

        # 在参数中增加必须的字段 (添加签名字段,其它字段都已在各自函数里添加)
        params['sign'] = self.get_sign(params)
        # print(params)

        # 发送请求
        payload = urlencode(params)

        try:
            # 使用会话重用技术，请求延时降低80%
            session = self.sessionDict[i]
            # print(url+payload)
            resp = session.request(method, url, params=payload)

            code = resp.status_code
            d = resp.json()

            if code == 200:
                callback(d, reqID)
            else:
                self.onError(code, d)
        except Exception as e:
            self.onError(type(e), e.message)

    #----------------------------------------------------------------------
    def run(self, i):
        """连续运行"""
        self.sessionDict[i] = requests.Session()

        while self.active:
            try:
                req = self.queue.get(block=True, timeout=1)  # 获取请求的阻塞为一秒
                self.processReq(req, i)
            except Empty:
                pass

    #----------------------------------------------------------------------
    def addReq(self, method, path, params, callback):
        """发送请求"""
        # 请求编号加1
        self.reqID += 1

        # 生成请求字典并放入队列中
        req = (method, path, params, callback, self.reqID)
        self.queue.put(req)

        # 返回请求编号
        return self.reqID

    ##----------------------------------------------------------------------

    def get_sign(self, data):
        if not isinstance(data, dict) or not self._secret:
            return ''
        string = ''
        for item in [(k, data[k]) for k in sorted(data.keys())]:
            if item[0] == 'api_key':
                continue
            string = '{}{}{}'.format(string, item[0], item[1])
        string = '{}{}'.format(string, self._secret)
        sign = hmac.new(bytes(self._secret.encode()), string.encode(), hashlib.sha512).hexdigest()
        return sign

    #----------------------------------------------------------------------
    def onError(self, code, msg):
        """错误推送"""
        print(code, msg)

    #----------------------------------------------------------------------
    def onData(self, data, reqID):
        """"""
        print(data, reqID)
