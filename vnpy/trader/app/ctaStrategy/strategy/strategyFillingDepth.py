# encoding: UTF-8


from __future__ import division
from vnpy.trader.app.ctaStrategy import ctaTemplate

from time import sleep
import random
from decimal import *


########################################################################
class FillingDepthStrategy(ctaTemplate):
    """基于Tick的交易策略"""
    className = 'FillingDepthStrategy'
    author = u'wc'

    # 常规变量：
    # 开关:是否进行买卖操作
    orderLimit = True
    # 委托单的价格
    commissionPrice = 0
    # 委托的单量
    volum = 0
    # tick计数:用于处理每隔多少个tick执行cancelOrder操作
    tickCount = 0
    # 列表存放OrderID
    orderList = []
    # 持仓数量
    pos = 0
    # 持仓价格
    posPrice = 0

    # 参数列表，保存了参数的名称
    paramList = ['name',
                 'className',
                 'author',
                 'vtSymbol',
                 'initDays',
                 'Ticksize',
                 'fixedSize'
                 ]

    # 变量列表，保存了变量的名称
    varList = ['inited',
               'trading',
               'pos',
               'posPrice'
               ]

    # 同步列表，保存了需要保存到数据库的变量名称
    syncList = ['pos',
                'posPrice']


    # ----------------------------------------------------------------------
    def __init__(self, liquidityEngine, setting):
        """Constructor"""
        super(FillingDepthStrategy, self).__init__(liquidityEngine, setting)
        self.orderList = []

    # ----------------------------------------------------------------------
    def onInit(self):
        """初始化策略（必须由用户继承实现）"""
        self.writeCtaLog(u'%s策略初始化' % self.name)
        self.putEvent()

    # ----------------------------------------------------------------------
    def onStart(self):
        """启动策略（必须由用户继承实现）"""
        self.writeCtaLog(u'%s策略启动' % self.name)
        self.putEvent()

    # ----------------------------------------------------------------------
    def onStop(self):
        """停止策略（必须由用户继承实现）"""
        self.writeCtaLog(u'%s策略停止' % self.name)
        self.putEvent()

    # ----------------------------------------------------------------------
    def onTick(self, tick):
        """收到行情TICK推送（必须由用户继承实现）"""
        self.tickCount += 1

        # 风险控制：存货判断: 当存货>1000或<-1000手时, 取消所有委托单并停止策略
        if (self.pos >= 10000 or self.pos <= -10000):
            # 关掉开关，防止异步下单
            self.orderLimit = False
            # 取消所有委托
            self.cancelAll()
            # 停止策略
            self.onStop()

        # 当不满足停止策略条件时,开始买+卖单填充区间,其中做多区间为:bid2-bid3| bid3-bid4| bid4-bid5,做空区间同理
        elif self.orderLimit:
            # 卖单
            # 在askPrice2与askPrice3之间1/2部分填充一个卖单
            l = self.sell(self.generatePrice(tick.askPrice2, tick.askPrice3), self.getRandomVolume(), False)
            # l = self.askOrder1 = self.sell(str("0.00000411"), 400, False)  # 测试pos---ask1
            self.orderList.extend(l)


            # 将开关设为false，表示这一次tick中暂时停止委托
            self.orderLimit = False

        # 当tick达到指定次数时,取消委托
        if(self.tickCount >= 70):
            # 遍历OrderID,取消委托
            for i in self.orderList:
                self.cancelOrder(i)
                sleep(0.8)
            # 将列表置空
            self.orderList = []
            # 将tick计数置空
            self.tickCount = 0
            # 开启下次下单
            self.orderLimit = True

    # ----------------------------------------------------------------------
    def onOrder(self, order):
        pass

    def onTrade(self, trade):
        self.posPrice = trade.price
        # 同步数据到数据库
        # self.saveSyncData()
        # 发出状态更新事件
        self.putEvent()

    # ----------------------------------------------------------------------
    def onBar(self, bar):
        pass

    # ----------------------------------------------------------------------
    def onStopOrder(self, so):
        """停止单推送"""
        pass

    def generatePrice(self, x, y):
        '''价格波动'''
        # self.commissionPrice = str(round(x + (y - x) / 2, 8))
        self.commissionPrice = str(x + (y - x) / 2)
        return str(Decimal(self.commissionPrice).quantize(Decimal('0.00000000')))
        # return self.commissionPrice


    def getRandomVolume(self):
        '''下单量波动'''
        self.volum = 300 + random.randint(1, 99)
        return self.volum