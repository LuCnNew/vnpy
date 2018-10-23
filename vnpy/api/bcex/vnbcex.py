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

from hashlib import md5
import json
import websocket
import time

Trading_Macro = 'https://www.bcex.top/Api_Order'
Market_Macro = 'https://www.bcex.top/Api_Market'
User_Macro = 'https://www.bcex.top/Api_User'

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

########################################################################
class BcexRestApi(object):
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
        if('getPriceList' in path):
            url = Market_Macro + path
        elif('userBalance' in path):
            url = User_Macro + path
        else:
          url = Trading_Macro + path

        # 在参数中增加必须的字段
        params['sign'] = self.get_sign(params)

        # 发送请求
        payload = urlencode(params)

        try:
            # 使用会话重用技术，请求延时降低80%
            session = self.sessionDict[i]
            resp = session.request(method, url, params=payload)

            code = resp.status_code
            d = resp.json()

            if code == 200:
                if('orderInfo' in url):
                    # if u qryorder, u need to tell onQryOrder this callback the order_id
                    callback(d, reqID, params['trust_id'])
                else:
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
        data = ['%s=%s' % i for i in sorted(data.items())]
        data = '&'.join(data) + '&secret_key=' + self._secret
        # use md5 to encryption and need to use hexdigest() function to convert the result
        # python3: u need to use data.encode();  python2: just data
        signature = md5(data.encode()).hexdigest()
        return signature

    #----------------------------------------------------------------------
    def onError(self, code, msg):
        """错误推送"""
        print(code, msg)

    #----------------------------------------------------------------------
    def onData(self, data, reqID):
        """"""
        print(data, reqID)
