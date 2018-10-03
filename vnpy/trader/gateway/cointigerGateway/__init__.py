# encoding: UTF-8

from __future__ import absolute_import
from vnpy.trader import vtConstant
from .cointigerGateway import CointigerGateway

gatewayClass = CointigerGateway
gatewayName = 'COINTIGER'
gatewayDisplayName = u'COINTIGERK'
gatewayType = vtConstant.GATEWAYTYPE_BTC
gatewayQryEnabled = True
