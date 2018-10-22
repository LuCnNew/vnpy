# encoding: UTF-8

from __future__ import absolute_import
from vnpy.trader import vtConstant
from .bcexGateway import BcexGateway

gatewayClass = BcexGateway
gatewayName = 'BCEX'
gatewayDisplayName = u'BCEX'
gatewayType = vtConstant.GATEWAYTYPE_BTC
gatewayQryEnabled = True
