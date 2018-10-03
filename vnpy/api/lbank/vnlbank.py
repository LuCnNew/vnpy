# encoding: utf-8

from __future__ import print_function
try:
    from urllib.parse import urlencode
except:
    from urllib import urlencode
import hashlib
import ssl
import json
import traceback
import requests
from queue import Queue, Empty
from threading import Thread
from multiprocessing.dummy import Pool
from time import time
import websocket

#官方API导入的包
from hashlib import md5
from base64 import b64encode
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5




#REST_HOST = "https://api.lbank.info/v1"
REST_HOST="https://api.lbkex.com/v1"
WEBSOCKET_HOST = 'ws://api.lbank.info/ws'
LBANK_ERROR_CODE = {

    '10000': 'Internal error',
    '10001': 'The necessary parameters can not be empty',
    '10002': 'Validation does not pass',
    '10003': 'Invalid parameter',
    '10004': 'User requests are too frequent',
    '10005': 'Secret key does not exist',
    '10006': 'User does not exist',
    '10007': 'Invalid sign',
    '10008': 'This transaction pair is not supported',
    '10009': 'The limit order should not be short of the price and the number of the orders',
    '10010': 'A single price or a single number must be more than 0',
    '10013': 'The minimum amount of sale that is less than the position of 0.001',
    '10014': 'Insufficient amount of money in account',
    '10015': 'Order type error',
    '10016': 'Insufficient account balance',
    '10017': 'Server exception',
    '10018': 'The number of order query entries should not be larger than 50 less than 1 bars',
    '10019': 'The number of withdrawal entries should not be greater than 3 less than 1',
    '10020': 'Minimum amount of sale less than 0.001',
    '10022': 'Access denied',
    '10025': 'Order filled',

}


class LBankError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def check_result(result):
    '''Raise LBank Error if it returned an error code'''
    if 'result' in result and result['result'] == 'false':
        code = result['error_code']
        msg = LBANK_ERROR_CODE.get(str(code), 'Unknown Error')
        raise LBankError(code, msg)
    else:
        return result


########################################################################
class LbankRestApi(object):
    """"""
    #----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self.apiKey = ''
        self.secretKey = ''

        self.active = False         # API工作状态
        self.reqID = 0              # 请求编号
        self.queue = Queue()        # 请求队列
        self.pool = None            # 线程池
        self.sessionDict = {}       # 连接池

    #----------------------------------------------------------------------
    def init(self, apiKey, secretKey):
        """初始化"""
        self._head = {'contentType': 'application/x-www-form-urlencoded'}
        self.apiKey = apiKey
        if secretKey:
            if len(secretKey) > 32:
                if secretKey.split('\n')[0] == '-----BEGIN RSA PRIVATE KEY-----':
                    pass
                else:
                    secretKey = '\n'.join([
                        '-----BEGIN RSA PRIVATE KEY-----',
                        secretKey,
                        '-----END RSA PRIVATE KEY-----'
                    ])

                secretKey = RSA.importKey(secretKey)
                self.signer = PKCS1_v1_5.new(secretKey)
            else:
                self.signer = None
                self.secretKey = secretKey
        else:
            self.signer = self.secretKey = None

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
        url = REST_HOST + path

        # 在参数中增加必须的字段
        params['api_key'] = self.apiKey
        params['sign'] = self.generateSignature(params)

        # 发送请求
        payload = urlencode(params)

        try:
            # 使用会话重用技术，请求延时降低80%
            session = self.sessionDict[i]
            resp = session.request(method, url, params=payload)
            #resp = requests.request(method, url, params=payload)

            code = resp.status_code
            d = resp.json()

            if code == 200:
                callback(d, reqID)
            else:
                self.onError(code, str(d))

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
    def generateSignature(self, parms):
        if self.signer:
            parms = ['%s=%s' % i for i in sorted(parms.items())]
            parms = '&'.join(parms).encode('utf-8')
            message = md5(parms).hexdigest().upper()

            digest = SHA256.new()
            digest.update(message.encode('utf-8'))
            signature = b64encode(self.signer.sign(digest))
        elif self.secretKey:
            parms = ['%s=%s' % i for i in sorted(parms.items())]
            parms = '&'.join(parms) + '&secret_key=' + self._private_key
            signature = md5(parms.encode('utf-8')).hexdigest().upper()
        else:
            raise LBankError(10005, LBANK_ERROR_CODE['10005'])
        return signature

    #----------------------------------------------------------------------
    def onError(self, code, msg):
        """错误推送"""
        print(code, msg)

    #----------------------------------------------------------------------
    def onData(self, data, reqID):
        """"""
        print(data, reqID)


########################################################################
class LbankWebsocketApi(object):
    """Websocket API"""

    #----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self.ws = None
        self.thread = None
        self.active = False

    #----------------------------------------------------------------------
    def start(self):
        """启动"""
        self.ws = websocket.create_connection(WEBSOCKET_HOST,
                                              sslopt={'cert_reqs': ssl.CERT_NONE})

        self.active = True
        self.thread = Thread(target=self.run)
        self.thread.start()

        self.onConnect()

    #----------------------------------------------------------------------
    def reconnect(self):
        """重连"""
        self.ws = websocket.create_connection(WEBSOCKET_HOST,
                                              sslopt={'cert_reqs': ssl.CERT_NONE})

        self.onConnect()

    #----------------------------------------------------------------------
    def run(self):
        """运行"""
        while self.active:
            try:
                stream = self.ws.recv()
                data = json.loads(stream)
                self.onData(data)
            except:
                msg = traceback.format_exc()
                self.onError(msg)
                self.reconnect()

    #----------------------------------------------------------------------
    def close(self):
        """关闭"""
        self.active = False

        if self.thread:
            self.ws.shutdown()
            self.thread.join()

    #----------------------------------------------------------------------
    def onConnect(self):
        """连接回调"""
        print('connected')

    #----------------------------------------------------------------------
    def onData(self, data):
        """数据回调"""
        print('-' * 30)
        l = data.keys()
        l.sort()
        for k in l:
            print(k, data[k])

    #----------------------------------------------------------------------
    def onError(self, msg):
        """错误回调"""
        print(msg)

    #----------------------------------------------------------------------
    def sendReq(self, req):
        """发出请求"""
        self.ws.send(json.dumps(req))


