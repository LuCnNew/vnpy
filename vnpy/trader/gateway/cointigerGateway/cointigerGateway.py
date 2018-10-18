# encoding: UTF-8

'''
vnpy.api.cointiger的gateway接入
'''


from __future__ import print_function

import requests
import json
from vnpy.api.cointiger import CointigerRestApi
from datetime import datetime
from copy import copy
from vnpy.trader.vtGateway import *
from vnpy.trader.vtFunction import getJsonPath
import numpy

directionMap = {}
directionMap[DIRECTION_LONG] = 'buy'
directionMap[DIRECTION_SHORT] = 'sell'
directionMapReverse = {v:k for k,v in directionMap.items()}

statusMapReverse = {}
statusMapReverse[0] = STATUS_NOTTRADED
statusMapReverse[1] = STATUS_NOTTRADED
statusMapReverse[2] = STATUS_ALLTRADED
statusMapReverse[3] = STATUS_PARTTRADED
statusMapReverse[4] = STATUS_CANCELLED

########################################################################
class CointigerGateway(VtGateway):
    """COINTIGER接口"""

    #----------------------------------------------------------------------
    def __init__(self, eventEngine, gatewayName='', config_dict= None):
        """Constructor"""
        super(CointigerGateway, self).__init__(eventEngine, gatewayName)

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
                                    # self.restApi.qryAccount,
                                    self.restApi.qryOrderNewSubmitted,
                                    self.restApi.qryOrderPartialFilled,
                                    self.restApi.qryOrderCanceled,
                                    self.restApi.qryOrderFilled,
                                    self.restApi.qryOrderExpired]
            # ]
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

    def get_depth(self, symbol, number):
        """创建一个查询深度函数,以供对敲左右手策略使用"""
        type = 'step0'
        api_url = 'https://api.cointiger.pro/exchange/trading/api'
        url = '{0}/market/depth?symbol={1}&type={2}'.format(api_url, symbol, type)
        # r = requests.request('GET', url, params=params)
        resultBids = []
        resultAsks = []
        with requests.Session() as session:
            data = session.get(url).json()
            if data:
                if data.get('code', None) == '0':

                    # Stitching orderbook format
                    bids = data['data']['depth_data']['tick']['buys']
                    for i in range(0, len(bids)):
                        a = float(bids[i][0])
                        bids[i][0] = a
                        bids[i][1] = int(bids[i][1])
                        resultBids.append(bids[i])
                    asks = data['data']['depth_data']['tick']['asks']
                    for k in range(0, len(asks)):
                        b = float(asks[k][0])
                        asks[k][0] = b
                        asks[k][1] = int(asks[k][1])
                        resultAsks.append(asks[k])
                    d = {}
                    d['bids'] = resultBids
                    d['asks'] = resultAsks
                    return d
                else:
                    return data
            else:
                return {}


########################################################################
class RestApi(CointigerRestApi):
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

        self.workingOrderDict = []

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
            tick.exchange = 'COINTIGER'
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
        self.localID += 1
        orderID = str(self.localID)
        vtOrderID = '.'.join([self.gatewayName, orderID])
        req = {
            'symbol': orderReq.symbol,
            'side': directionMap[orderReq.direction].upper(),
            'price': str(round(orderReq.price, 8)),
            'volume': str(int(orderReq.volume)),
            'type': 1,
            'time': (int)(time.time()),
            'api_key': self._api_key
        }

        reqid = self.addReq('POST', '/v2/order?', req, self.onSendOrder)

        # 缓存委托数据对象
        order = VtOrderData()
        order.gatewayName = self.gatewayName
        order.symbol = orderReq.symbol
        order.exchange = EXCHANGE_COINTIGER
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
            '''
            # v1 version cancel
            req = {
                'symbol': order.symbol,
                'order_id': sysID,
                'time': (int)(time.time()),
                'api_key': self._api_key
            }
            self.addReq('DELETE', '/order', req, self.onCancelOrder)
            '''

            # v2 version cancel
            req = {
                'orderIdList': str({order.symbol: [str(sysID)]}),
                'time': int(time.time()),
                'api_key': self._api_key
            }
            self.addReq('POST', '/v2/order/batch_cancel', req, self.onCancelOrder)
        else:
            self.cancelDict[localID] = cancelOrderReq

    #----------------------------------------------------------------------
    def qryContract(self):
        """"""
        self.addReq('GET', '/v2/currencys', {}, self.onQryContract)

    # ----------------------------------------------------------------------
    def qryOrder(self, state):
        """"""
        if self.workingOrderDict:
            startOrder = numpy.min(self.workingOrderDict)
        else:
            startOrder = None
        for symbol in self.symbols:
            req = {
                'symbol': symbol,
                'states': state,
                'time': int(time.time()),
                'from': startOrder,
                'api_key': self._api_key
            }
            self.addReq('GET', '/v2/order/orders', req, self.onQryOrder)

    # ----------------------------------------------------------------------
    def qryOrderPartialFilled(self):
        """"""
        self.qryOrder('part_filled')

    # ----------------------------------------------------------------------
    def qryOrderNewSubmitted(self):
        """"""
        self.qryOrder('new')

    # ----------------------------------------------------------------------
    def qryOrderFilled(self):
        """"""
        self.qryOrder('filled')

    # ----------------------------------------------------------------------
    def qryOrderCanceled(self):
        """"""
        self.qryOrder('canceled')

    # ----------------------------------------------------------------------
    def qryOrderExpired(self):
        """"""
        self.qryOrder('expired')


    #----------------------------------------------------------------------
    # def qryWorkingOrder(self):
    #     """"""
    #     for symbol in self.symbols:
    #         req = {
    #             'symbol': symbol,
    #             'time': int(time.time()),
    #             'states': 'new',
    #             'api_key': self._api_key
    #         }
    #         self.addReq('GET', '/v2/order/orders', req, self.onQryOrder)

    #----------------------------------------------------------------------
    def qryAccount(self):
        """"""
        # Temporarily unrealized
        for symbol in self.symbols:
            # note: there dont give the explicit symbol because you can only input coin rather than symbol--> eg: coin:ptt  symbol:ptteth
            # you can get all coin by dont input coin, then handle the output(a dict) in onQryAccount to get what coin` account you want

            req = {'api_key': self._api_key,
                   'time': int(time.time())
                   }
        self.addReq('GET', '/user/balance?', req, self.onQryAccount)

    #----------------------------------------------------------------------
    def qryDepth(self):
        """"""
        for symbol in self.symbols:
            req = {
                'symbol': symbol,
                'type': 'step0'
            }
            i = self.addReq('GET', '/market/depth?', req, self.onQryDepth)
            self.reqSymbolDict[i] = symbol

    #----------------------------------------------------------------------
    def qryTicker(self):
        """"""
        for symbol in self.symbols:
            req = {'symbol': symbol}
            i = self.addReq('GET', '/market/detail?', req, self.onQryTicker)
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
        # u need to remember the order_id that to cancel, and keep 2 element
        self.workingOrderDict.append(sysID)
        if(len(self.workingOrderDict) > 2):
            self.workingOrderDict = self.workingOrderDict[2:]

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
        # pass

    #----------------------------------------------------------------------
    def onError(self, code, error):
        """"""
        msg = u'发生异常，错误代码：%s，错误信息：%s' % (code, error)
        self.writeLog(msg)

    #----------------------------------------------------------------------
    def onQryOrder(self, data, reqid):
        """"""
        if 'data' not in data:
            return

        if not isinstance(data['data'], list):
            return

        # data['data'].reverse()

        for d in data['data']:
            orderUpdated = False
            tradeUpdated = False

            # 获取所有委托对象(新单就是当前委托,当它撤销后就变成了历史委托了,所以这个单是被qry了多次的)
            sysID = d['id']
            # print(sysID)
            if sysID in self.orderDict:
                order = self.orderDict[sysID]
            else:
                order = VtOrderData()
                order.gatewayName = self.gatewayName

                order.symbol = d['symbol']
                order.exchange = EXCHANGE_COINTIGER
                order.vtSymbol = '.'.join([order.symbol, order.exchange])

                self.localID += 1
                localID = str(self.localID)
                self.localSysDict[localID] = sysID

                order.orderID = localID
                order.vtOrderID = '.'.join([order.gatewayName, order.orderID])

                order.direction = directionMapReverse[d['type'].split('-')[0]]
                order.price = float(d['price'])
                order.totalVolume = float(d['volume'])

                dt = datetime.fromtimestamp(d['ctime'] / 1000)
                order.orderTime = dt.strftime('%H:%M:%S')

                self.orderDict[sysID] = order
                orderUpdated = True

            newTradedVolume = float(d['deal_volume'])
            newStatus = statusMapReverse[d['status']]

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

    #!!! unrealized----------------------------------------------------------------------
    def onQryAccount(self, data, f):
        """"""
        asset = data['data']

        for currency in asset.keys():
            account = VtAccountData()
            account.gatewayName = self.gatewayName

            account.accountID = currency
            account.vtAccountID = '.'.join([self.gatewayName, account.accountID])
            account.balance = float(asset[currency])
            account.available = float(free[currency])

            self.gateway.onAccount(account)

    #----------------------------------------------------------------------
    def onQryContract(self, data, reqid):
        """"""

        for d in data["data"]["eth-partition"]:
            contract = VtContractData()
            contract.gatewayName = self.gatewayName

            # Stitching string like: eoseth , ptteth
            s_base = str(d['baseCurrency'])
            s_quote = str(d['quoteCurrency'])
            contract.symbol = '{}{}'.format(s_base, s_quote)
            # print(contract.symbol)
            contract.exchange = EXCHANGE_COINTIGER
            contract.vtSymbol = '.'.join([contract.symbol, contract.exchange])
            contract.name = contract.vtSymbol
            contract.productClass = PRODUCT_SPOT
            contract.priceTick = pow(10, -int(d['pricePrecision']))
            contract.size = 1

            self.gateway.onContract(contract)

        self.writeLog(u'合约信息查询完成')

    #----------------------------------------------------------------------
    def onQryTicker(self, data, reqid):
        """"""
        ticker = data['data']['trade_ticker_data']['tick']

        symbol = self.reqSymbolDict.pop(reqid)
        tick = self.tickDict[symbol]

        tick.highPrice = float(ticker['high'])
        tick.lowPrice = float(ticker['low'])
        tick.closePrice = float(ticker['close'])
        tick.openPrice = float(ticker['open'])
        tick.volume = float(ticker['vol'])


        tick.datetime = datetime.fromtimestamp(int(data['data']['trade_ticker_data']['ts']/1000))
        tick.date = tick.datetime.strftime('%Y%m%d')
        tick.time = tick.datetime.strftime('%H:%M:%S')

        if tick.closePrice:
            self.gateway.onTick(copy(tick))

    #----------------------------------------------------------------------
    def onQryDepth(self, data, reqid):
        """"""
        symbol = self.reqSymbolDict.pop(reqid)
        tick = self.tickDict[symbol]

        bids = data['data']['depth_data']['tick']['buys']
        asks = data['data']['depth_data']['tick']['asks']

        tick.bidPrice1, tick.bidVolume1 = bids[0]
        tick.bidPrice2, tick.bidVolume2 = bids[1]
        tick.bidPrice3, tick.bidVolume3 = bids[2]
        tick.bidPrice4, tick.bidVolume4 = bids[3]
        tick.bidPrice5, tick.bidVolume5 = bids[4]

        # price is unicode type, need convert to float then you can make arithmetic
        tick.bidPrice1 = float(tick.bidPrice1.encode("utf-8"))
        tick.bidPrice2 = float(tick.bidPrice2.encode("utf-8"))
        tick.bidPrice3 = float(tick.bidPrice3.encode("utf-8"))
        tick.bidPrice4 = float(tick.bidPrice4.encode("utf-8"))
        tick.bidPrice5 = float(tick.bidPrice5.encode("utf-8"))

        tick.askPrice1, tick.askVolume1 = asks[0]
        tick.askPrice2, tick.askVolume2 = asks[1]
        tick.askPrice3, tick.askVolume3 = asks[2]
        tick.askPrice4, tick.askVolume4 = asks[3]
        tick.askPrice5, tick.askVolume5 = asks[4]

        tick.askPrice1 = float(tick.askPrice1.encode("utf-8"))
        tick.askPrice2 = float(tick.askPrice2.encode("utf-8"))
        tick.askPrice3 = float(tick.askPrice3.encode("utf-8"))
        tick.askPrice4 = float(tick.askPrice4.encode("utf-8"))
        tick.askPrice5 = float(tick.askPrice5.encode("utf-8"))

        if tick.bidPrice1:
            self.gateway.onTick(copy(tick))

