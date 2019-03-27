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
apiKey = 'b0a6f4873795ba3b5ab305ad6078f5ce'
secretKey = '''-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCvuoZj82Ab2+Ol
T0dUhvjZ3tJA0umC0vvwidWoBRBQ8BPEcQJuL0I5cksDi1yXtr1yoGttSd0+Omj/
+nnK/60tQgdya40tjWX7aY1MUIGsgXuog1nT2thO1VWNv9sXhdzQ5D84g3IrekHJ
4p/DY08EMefahbQhT12kXIMRgx/QGOpzPgcsPDGs9BB5IN8qdeJaCMTlIyjN4T4T
+P8KevqPUmoq13qLkMuFEnbpunKEbOvEOe9g0wzJ8v8cxh2HCqwNMLv0og8iBDDf
b5nzTg7FPZdm45WxCpfy0evH+x7qUFhty8lqC1GTIyLE6YZ03dR5ZQWlXHwbQaTh
kO6uF3YbAgMBAAECggEAc2Xc7PQcsA7FPoCCSgrcjk5Z6gHXIHcmxT3ulYjFvzD4
+i5wNyVHquvYQPqaknKJlCWuhjVUWZIH89lrc5hVA/xxYX0pV7mcN+6HwI65qSva
pb2kFpCHLbXAmfZcjOT2LiNFNPp01gJSA56T5b5oXEvdgs38jUdOKioqVCy0jnVH
RP5r3N24I9me1aXeQLhwR+jr2mCJP6gWwfiA2lyfxyuKeKrc7tcRoG0YAu2iSEvv
QIMalBBaPmIVgVfTcJOUXPAg7kq9F60fqMkZ96h//7Gmt1rxTbeOKXctTOOGMNsz
WNOKNKxb6/Udrme/ZQ1mxLXu2ZQeusNGA3FXZiZbIQKBgQDfhm15GWDQSnQBFk7O
Iqthz3hAhS3c9u9g+OUY/jlRYVKRLad3IehIkG7V8wh175TxiNGKyy/dCQl6PZkw
Km/9daH/W+SP3OWab/jJjYZD1gOkMBoexhyxZbm5qJnNyNdJiJWbkrt4HQ5+sEPU
9Nrh5h4iGT4l9MZgHlHnEx9JkQKBgQDJQmbS1EPGNlK3sYyMa3/bI4mcyQEL58hY
+WoS3qEw23bAcFiT4GlX0KpDuQriP5cgBPdX9gmCMY96rf+T/zoCa1iqs5HAI/S+
q7RmJK2/MPU7Z0SpykkVeMXamQ4azVGnrFJ1GeyiD+xQKfUrtF1Ex/ahTydh1We8
SPOZcEkO6wKBgQClTFMOt/7JahXJbAbRGABnb7b898AH5TD3JHi/d9lJXlBh/kIW
rqOJbg4Y+AYsuQULbWOQYVw++Fzi4kSzwt5YsLIhFoK7BN9iyyVPX/KHne/Jbq0S
Tu2PHqwvKQi8jqbuwSvqBaPPWqWKeK1hAcYQQk3MZ6B3D0HYePOWj6SWkQKBgEwO
wwsD2sUKfIIdIA9lBMGNEZFlyPZ11poBT9vntKThG2SoUGE6GrVsDxxezsUn4PXh
ypO8UGWaUy26me6VMpf9d1mzWO5y6CgyfY9oZxzs5JBZe3JrFul9ZdAxrUnls+kY
z2SfsnSgbd7xrEyi8ehvZT4ayrhHTNez/hNLguCXAoGAe1S4HhwBgRUpgeCUndo5
hyC+P/1QkyqWRqTbtUmPpimuj4cW6SMTkPcfiF0csWLTLxumtelxp94kjKF9m5G+
lYcxTJxUN3M5AK+SFlx5U56+KifHdus+86UTg+jUUE0YaaB1McEvJYk77k2A4SfW
lqnnF9f+ILqo1O3MGP9A1eo=
-----END PRIVATE KEY-----'''
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
        secret = secretKey
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
