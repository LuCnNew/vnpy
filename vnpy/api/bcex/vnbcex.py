# encoding: utf-8

from __future__ import print_function
try:
    import urllib.parse as _urlencode
except ImportError:
    import urllib as _urlencode
import collections
import urllib3
import requests
from queue import Queue, Empty
from multiprocessing.dummy import Pool
import base64
import json
from OpenSSL import crypto

Trading_Macro = 'https://api.bcex.vip/api_market'
Market_Macro = 'https://api.bcex.vip/api_market'
User_Macro = 'https://api.bcex.vip/api_market'

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
        self._api_key = apiKey
        self._secret = secretKey

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
        sign = self.get_sign(params)

        headers = {
            'Content-type':'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.71 Safari/537.36'
                   }
        try:
            # 使用会话重用技术，请求延时降低80%
            session = self.sessionDict[i]
            resp = session.request(method, url, headers=headers, data=sign)
            code = resp.status_code
            d = resp.json()

            if code == 200:
                if('/getOrderByOrderNo' in url):
                    # if u qryorder, u need to tell onQryOrder this callback the order_id
                    callback(d, reqID, params['order_no'])
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
        secret = self._secret
        query = collections.OrderedDict(sorted(data.items(), key=lambda t: t[0]))
        json_str = json.dumps(query, separators=(',', ':'))
        key = crypto.load_privatekey(crypto.FILETYPE_PEM, secret)
        signature_base64 = base64.b64encode(crypto.sign(key, bytes(json_str, encoding="utf8"), 'RSA-SHA1'))
        signature_str_tmp = str(signature_base64, encoding='utf-8')
        query['sign'] = _urlencode.quote(signature_str_tmp, safe="~()*!.'")
        body = json.dumps(query, separators=(',', ':'))
        return body

    #----------------------------------------------------------------------
    def onError(self, code, msg):
        """错误推送"""
        print(code, msg)

    #----------------------------------------------------------------------
    def onData(self, data, reqID):
        """"""
        print(data, reqID)
