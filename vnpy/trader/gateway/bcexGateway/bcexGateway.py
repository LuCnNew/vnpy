# encoding: UTF-8

'''
vnpy.api.bcex的gateway接入
'''


from __future__ import print_function

import requests
import json
# there u need to change bcex
from vnpy.api.bcex import BcexRestApi

from datetime import datetime
from copy import copy
from vnpy.trader.vtGateway import *
from vnpy.trader.vtFunction import getJsonPath
from urllib.parse import urlencode
import queue

import numpy

directionMap = {}
directionMap[DIRECTION_LONG] = 'buy'
directionMap[DIRECTION_SHORT] = 'sale'
directionMapReverse = {v:k for k,v in directionMap.items()}

statusMapReverse = {}
statusMapReverse[0] = STATUS_NOTTRADED
statusMapReverse[1] = STATUS_PARTTRADED
statusMapReverse[2] = STATUS_ALLTRADED
statusMapReverse[3] = STATUS_CANCELLED

########################################################################
class BcexGateway(VtGateway):
    """BCEX接口"""

    #----------------------------------------------------------------------
    def __init__(self, eventEngine, gatewayName='', config_dict= None):
        """Constructor"""
        super(BcexGateway, self).__init__(eventEngine, gatewayName)

        self.restApi = RestApi(self)

        self.qryEnabled = False         # 是否要启动循环查询

        if config_dict == None:
            self.fileName = self.gatewayName + '_connect.json'
            self.filePath = getJsonPath(self.fileName, __file__)
        else:
            self.fileName = config_dict['file_name']
            self.filePath = getJsonPath(self.fileName, __file__)


            #----------------------------------------------------------------------
    def connect(self):
        """连接"""
        try:
            f = open(self.filePath)
        except IOError:
            log = VtLogData()
            log.gatewayName = self.gatewayName
            log.logContent = u'读取连接配置出错，请检查'
            self.onLog(log)
            return

        # 解析json文件
        setting = json.load(f)
        try:
            apiKey = str(setting['apiKey'])
            secretKey = str(setting['secretKey'])
            symbols = setting['symbols']
        except KeyError:
            log = VtLogData()
            log.gatewayName = self.gatewayName
            log.logContent = u'连接配置缺少字段，请检查'
            self.onLog(log)
            return

        # 创建行情和交易接口对象
        self.restApi.connect(apiKey, secretKey, symbols)

        # 初始化并启动查询
        self.initQuery()

    #----------------------------------------------------------------------
    def subscribe(self, subscribeReq):
        """订阅行情"""
        pass

    #----------------------------------------------------------------------
    def sendOrder(self, orderReq):
        """发单"""
        return self.restApi.sendOrder(orderReq)

    #----------------------------------------------------------------------
    def cancelOrder(self, cancelOrderReq):
        """撤单"""
        self.restApi.cancelOrder(cancelOrderReq)

    #----------------------------------------------------------------------
    def close(self):
        """关闭"""
        self.restApi.close()

    #----------------------------------------------------------------------
    def initQuery(self):
        """初始化连续查询"""

        if self.qryEnabled:
            self.qryFunctionList = [
                                    self.restApi.qryMarketData,
                                    self.restApi.qryAccount,
                                    self.restApi.qryOrder
            ]
            # 需要循环的查询函数列表

            self.qryCount = 0           # 查询触发倒计时
            self.qryTrigger = 1         # 查询触发点
            self.qryNextFunction = 0    # 上次运行的查询函数索引

            self.startQuery()

    #----------------------------------------------------------------------
    def query(self, event):
        """注册到事件处理引擎上的查询函数"""
        self.qryCount += 1

        if self.qryCount > self.qryTrigger:
            # 清空倒计时
            self.qryCount = 0

            # 执行查询函数
            function = self.qryFunctionList[self.qryNextFunction]
            function()

            # 计算下次查询函数的索引，如果超过了列表长度，则重新设为0
            self.qryNextFunction += 1
            if self.qryNextFunction == len(self.qryFunctionList):
                self.qryNextFunction = 0

    #----------------------------------------------------------------------
    def startQuery(self):
        """启动连续查询"""
        self.eventEngine.register(EVENT_TIMER, self.query)

    #----------------------------------------------------------------------
    def setQryEnabled(self, qryEnabled):
        """设置是否要启动循环查询"""
        self.qryEnabled = qryEnabled

    # ----------------------------------------------------------------------
    def get_depth(self, symbol, number):
        """创建一个查询深度函数,以供对敲左右手策略使用"""
        api_url = 'https://www.bcex.top/Api_Order/depth'
        req = {
            'symbol': symbol
        }

        payload = urlencode(req)
        session = requests.Session()
        resp = session.request('POST', api_url, params=payload)
        data = resp.json()

        d = {}
        d['asks'] = data['data']['asks'][::-1]
        d['bids'] = data['data']['bids']
        return d

########################################################################
class RestApi(BcexRestApi):
    """REST API实现"""

    #----------------------------------------------------------------------
    def __init__(self, gateway):
        """Constructor"""
        super(RestApi, self).__init__()

        self.gateway = gateway                  # gateway对象
        self.gatewayName = gateway.gatewayName  # gateway对象名称

        self.localID = 0
        self.tradeID = 0

        self.orderDict = {}         # sysID:order
        self.localSysDict = {}      # localID:sysID
        self.reqOrderDict = {}      # reqID:order
        self.cancelDict = {}        # localID:req

        self.tickDict = {}          # symbol:tick
        self.reqSymbolDict = {}

        self.workingOrderDict = {}

    #----------------------------------------------------------------------
    def connect(self, apiKey, apiSecret, symbols):
        """连接服务器"""
        self.init(apiKey, apiSecret)
        self.start()

        self.symbols = symbols
        for symbol in symbols:
            tick = VtTickData()
            tick.gatewayName = self.gatewayName
            tick.symbol = symbol
            tick.exchange = 'BCEX'
            tick.vtSymbol = '.'.join([tick.symbol, tick.exchange])
            self.tickDict[symbol] = tick

        self.writeLog(u'REST API启动成功')
        self.qryContract()

    #----------------------------------------------------------------------
    def writeLog(self, content):
        """发出日志"""
        log = VtLogData()
        log.gatewayName = self.gatewayName
        log.logContent = content
        self.gateway.onLog(log)

    #----------------------------------------------------------------------
    def sendOrder(self, orderReq):
        """"""
        # u need to clear the workingOrderDict to maintain this Dict just have the order_id u send just now
        self.workingOrderDict = {}
        self.localID += 1
        orderID = str(self.localID)
        vtOrderID = '.'.join([self.gatewayName, orderID])
        req = {
            'api_key': self._api_key,
            'symbol': orderReq.symbol,
            'type': directionMap[orderReq.direction],
            'price': str(round(orderReq.price, 8)),
            'number': str(int(orderReq.volume))
        }

        reqid = self.addReq('POST', '/coinTrust', req, self.onSendOrder)

        # 缓存委托数据对象
        order = VtOrderData()
        order.gatewayName = self.gatewayName
        order.symbol = orderReq.symbol
        order.exchange = EXCHANGE_BCEX
        order.vtSymbol = '.'.join([order.symbol, order.exchange])
        order.orderID = orderID
        order.vtOrderID = vtOrderID
        order.price = orderReq.price
        order.totalVolume = orderReq.volume
        order.direction = orderReq.direction
        order.status = STATUS_UNKNOWN

        self.reqOrderDict[reqid] = order

        return vtOrderID

    #----------------------------------------------------------------------
    def cancelOrder(self, cancelOrderReq):
        """"""
        localID = cancelOrderReq.orderID

        if localID in self.localSysDict:
            sysID = self.localSysDict[localID]
            order = self.orderDict[sysID]

            req = {
                'api_key': self._api_key,
                'symbol': order.symbol,
                'order_id': sysID
            }
            self.addReq('POST', '/cancel', req, self.onCancelOrder)
        else:
            self.cancelDict[localID] = cancelOrderReq

        # self.workingOrderDict.pop(sysID)

    #----------------------------------------------------------------------
    def qryContract(self):
        """"""
        self.addReq('GET', '/getPriceList', {}, self.onQryContract)

    # ----------------------------------------------------------------------
    def qryOrder(self):
        """"""
        for symbol in self.symbols:
            for sysID in self.workingOrderDict:
                req = {
                    'api_key': self._api_key,
                    'symbol': symbol,
                    'trust_id': sysID
                }
                self.addReq('POST', '/orderInfo', req, self.onQryOrder)

    #----------------------------------------------------------------------
    def qryAccount(self):
        """"""
        for symbol in self.symbols:
            req = {'api_key': self._api_key,
                   }
        self.addReq('POST', '/userBalance', req, self.onQryAccount)

    #----------------------------------------------------------------------
    def qryDepth(self):
        """"""
        for symbol in self.symbols:
            req = {
                'symbol': symbol,
            }
            i = self.addReq('POST', '/depth', req, self.onQryDepth)
            self.reqSymbolDict[i] = symbol

    #----------------------------------------------------------------------
    def qryTicker(self):
        """"""
        for symbol in self.symbols:
            req = {'symbol': symbol
            }
            i = self.addReq('POST', '/ticker', req, self.onQryTicker)
            self.reqSymbolDict[i] = symbol

    #----------------------------------------------------------------------
    def qryMarketData(self):
        """"""
        self.qryDepth()
        self.qryTicker()

    #----------------------------------------------------------------------
    def onSendOrder(self, data, reqid):
        """"""
        order = self.reqOrderDict[reqid]
        localID = order.orderID
        sysID = data['data']['order_id']

        self.workingOrderDict[sysID] = order

        self.localSysDict[localID] = sysID
        self.orderDict[sysID] = order
        self.gateway.onOrder(order)

        # 发出等待的撤单委托
        if localID in self.cancelDict:
            req = self.cancelDict[localID]
            self.cancelOrder(req)
            del self.cancelDict[localID]

    #----------------------------------------------------------------------
    def onCancelOrder(self, data, reqid):
        """"""
        # process the data when a canceled action happend
        self.writeLog(str(data))

    #----------------------------------------------------------------------
    def onError(self, code, error):
        """"""
        msg = u'发生异常，错误代码：%s，错误信息：%s' % (code, error)
        self.writeLog(msg)

    #----------------------------------------------------------------------
    def onQryOrder(self, data, reqid, trust_id = 0):
        """"""
        # print("status:", data['data']['number'], data['data']['status'])

        if 'data' not in data.keys():
            return

        # if not isinstance(data['data'], list):
        #     return

        # data['data'].reverse()

        # for d in data['data']:
        orderUpdated = False
        tradeUpdated = False

        # 获取所有委托对象
        # sysID = d['id']
        # for i in self.workingOrderDict:

        sysID = trust_id

        # print(sysID)
        if sysID in self.orderDict:
            order = self.orderDict[sysID]
        else:
            order = VtOrderData()
            order.gatewayName = self.gatewayName

            coin_from = str(data['data']['coin_from'])
            coin_to = str(data['data']['coin_to'])
            # order.symbol = str(coin_from + coin_to)
            order.symbol = str(coin_from + '2' + coin_to)

            order.exchange = EXCHANGE_BCEX
            order.vtSymbol = '.'.join([order.symbol, order.exchange])

            self.localID += 1
            localID = str(self.localID)
            self.localSysDict[localID] = sysID

            order.orderID = localID
            order.vtOrderID = '.'.join([order.gatewayName, order.orderID])

            # order.direction = directionMapReverse[d['type'].split('-')[0]]
            order.price = float(data['data']['price'])
            order.totalVolume = float(data['data']['number'])

            dt = datetime.fromtimestamp(int(d['created']) / 1000)
            order.orderTime = dt.strftime('%H:%M:%S')

            self.orderDict[sysID] = order
            orderUpdated = True

        newTradedVolume = float(data['data']['numberdeal'])
        newStatus = statusMapReverse[int(data['data']['status'])]

        if newTradedVolume != float(order.tradedVolume) or newStatus != order.status:
            orderUpdated = True

        if newTradedVolume != float(order.tradedVolume):
            tradeUpdated = True
            newVolume = newTradedVolume - order.tradedVolume

        order.tradedVolume = newTradedVolume
        order.status = newStatus
        # print(newStatus)

        # 若有更新才推送
        if orderUpdated:
            self.gateway.onOrder(order)

        if tradeUpdated:
            # 推送成交
            trade = VtTradeData()
            trade.gatewayName = order.gatewayName

            trade.symbol = order.symbol
            trade.vtSymbol = order.vtSymbol

            trade.orderID = order.orderID
            trade.vtOrderID = order.vtOrderID

            self.tradeID += 1
            trade.tradeID = str(self.tradeID)
            trade.vtTradeID = '.'.join([self.gatewayName, trade.tradeID])

            trade.direction = order.direction
            trade.price = order.price
            trade.volume = newTradedVolume
            trade.tradeTime = datetime.now().strftime('%H:%M:%S')

            self.gateway.onTrade(trade)

    # ----------------------------------------------------------------------
    def onQryAccount(self, data, f):
        """"""
        asset = data['data']
        if('eth_lock' in asset):
            eth_lock = asset['eth_lock']
        if ('eth_over' in asset):
            eth_over = asset['eth_over']
        if('ptt_lock' in asset):
            ptt_lock = asset['ptt_lock']
        if('ptt_over' in asset):
            ptt_over = asset['ptt_over']

        # eth account
        account = VtAccountData()
        account.gatewayName = self.gatewayName
        account.accountID = 'eth'
        account.vtAccountID = '.'.join([self.gatewayName, account.accountID])
        account.available = float(eth_over.encode("utf-8"))
        self.gateway.onAccount(account)

        # ptt account
        account = VtAccountData()
        account.gatewayName = self.gatewayName
        account.accountID = 'ptt'
        account.vtAccountID = '.'.join([self.gatewayName, account.accountID])
        account.available = float(ptt_over.encode("utf-8"))
        self.gateway.onAccount(account)

    #----------------------------------------------------------------------
    def onQryContract(self, data, reqid):
        """"""

        for d in data['eth']:
            contract = VtContractData()
            contract.gatewayName = self.gatewayName

            # Stitching string like: eoseth , ptteth
            s_base = str(d['coin_to'])
            s_quote = str(d['coin_from'])
            # contract.symbol = '{}2{}'.format(s_quote, s_base)
            contract.symbol = '{}2{}'.format(s_base, s_quote)
            contract.exchange = EXCHANGE_BCEX
            contract.vtSymbol = '.'.join([contract.symbol, contract.exchange])
            contract.name = contract.vtSymbol
            contract.productClass = PRODUCT_SPOT
            contract.size = 1

            self.gateway.onContract(contract)

        self.writeLog(u'合约信息查询完成')

    #----------------------------------------------------------------------
    def onQryTicker(self, data, reqid):
        """"""
        ticker = data['data']

        symbol = self.reqSymbolDict.pop(reqid)
        tick = self.tickDict[symbol]

        tick.highPrice = ticker['high']
        tick.lowPrice = ticker['low']
        tick.lastPrice = ticker['last']
        tick.volume = ticker['vol']

        if tick.highPrice:
            self.gateway.onTick(copy(tick))

    #----------------------------------------------------------------------
    def onQryDepth(self, data, reqid):
        """"""
        symbol = self.reqSymbolDict.pop(reqid)
        tick = self.tickDict[symbol]

        bids = data['data']['bids']
        asks = data['data']['asks']
        l = len(asks)

        tick.bidPrice1, tick.bidVolume1 = bids[0]
        tick.bidPrice2, tick.bidVolume2 = bids[1]
        tick.bidPrice3, tick.bidVolume3 = bids[2]
        tick.bidPrice4, tick.bidVolume4 = bids[3]
        tick.bidPrice5, tick.bidVolume5 = bids[4]

        tick.askPrice1, tick.askVolume1 = asks[l-1]
        tick.askPrice2, tick.askVolume2 = asks[l-2]
        tick.askPrice3, tick.askVolume3 = asks[l-3]
        tick.askPrice4, tick.askVolume4 = asks[l-4]
        tick.askPrice5, tick.askVolume5 = asks[l-5]

        if tick.bidPrice1:
            self.gateway.onTick(copy(tick))

