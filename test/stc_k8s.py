

##############################################################################
# Copyright (c) 2018 Spirent Communications and others.
#
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the Apache License, Version 2.0
# which accompanies this distribution, and is available at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Author: qiang.dai@spirent.com
#
##############################################################################

import logging
import time
import datetime
import sys
import json

from stcrestclient import stchttp

logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stdout)
logger.addHandler(hdlr=handler)
logger.setLevel(logging.DEBUG)

class SimpleTrafficTest(object):

    def _signin_aion(self):
        #aion_addr = "spirent.spirentaion.com"   #34.220.75.88
        aion_addr = "https://spirent.spirentaion.com"
        workspace = "spirent"
        username = "qiang.dai@spirent.com"
        password = "openstack"

        self.stc.perform("TemevaSignInCommand", server=aion_addr, username=username, password=password)
        self.stc.perform("TemevaSetWorkspaceCommand", workspace=workspace)

    def _signout_aion(self):
        self.stc.perform("TemevaSignOutCommand")

    def __init__(self, labserver_ip,
                 stcv_west_mgmt_ip, stcv_west_test_port_ip,
                 stcv_east_mgmt_ip, stcv_east_test_port_ip,
                 dut_left_ip, dut_right_ip,
                 labserver_port=80):
        self.labserver_ip = labserver_ip

        self.west_stcv = {
            "mgmt_ip": stcv_west_mgmt_ip,
            "test_port_ip": stcv_west_test_port_ip,
            "gw_ip": dut_left_ip,
            "port_location": "//" + stcv_west_mgmt_ip + "/1/1",
            "port": None,
            "gen": None,
            "ana": None,
            "result": None
        }
        self.east_stcv = {
            "mgmt_ip": stcv_east_mgmt_ip,
            "test_port_ip": stcv_east_test_port_ip,
            "gw_ip": dut_right_ip,
            "port_location": "//" + stcv_east_mgmt_ip + "/1/1",
            "port": None,
            "gen": None,
            "ana": None,
            "result": None
        }

        self.stc = stchttp.StcHttp(labserver_ip, port=labserver_port)

        self.user_name = "csu_user"
        time_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        test_name = "simpletraffic-" + time_str
        sess_id = test_name + " - " + self.user_name
        sess_list = self.stc.sessions()
        logger.debug("sess_list: %s", sess_list)
        if sess_id not in sess_list:
            try:
                sess_id = self.stc.new_session(self.user_name, test_name)
            except Exception as e:
                logger.error("create session fail, but ignore it as it's already there.")
                while True:
                    sesses = self.stc.sessions()
                    if sess_id in sesses:
                        logger.info("session created!")
                        break
                    else:
                        logger.info("session not created!")
                        time.sleep(3)
        self.stc.join_session(sess_id)

        self._signin_aion()

        self.sys = "system1"
        self.project = self.stc.get(self.sys, "children-project")

        return

    def __del__(self):
        self.end_session()

    def end_session(self):
        self.stc.disconnectall()
        self._signout_aion()

        sess_list = self.stc.sessions()
        for sess_id in sess_list:
            self.stc.end_session(sid=sess_id)

    def get_port_location(self):
        port_list = []
        phys_chassis_mgr = self.stc.get("system1", "children-physicalchassismanager")
        phys_chassis_list = self.stc.get(phys_chassis_mgr, "children-physicalchassis").split(" ")
        logger.debug("phys_chassis_list: %s" % phys_chassis_list)

        for phys_chassis in phys_chassis_list:
            hostname = self.stc.get(phys_chassis, "hostname")
            phys_mod_list = self.stc.get(phys_chassis, "children-physicaltestmodule").split()
            for phys_mod in phys_mod_list:
                slot = self.stc.get(phys_mod, "index")
                port_group_list = self.stc.get(phys_mod, "children-physicalportgroup").split()
                for port_group in port_group_list:
                    phys_pg = self.stc.get(port_group, "index")
                    phys_port_list = self.stc.get(port_group, "children-physicalport").split()
                    for phys_port in phys_port_list:
                        port_index = self.stc.get(phys_port, "index")
                        loc = self.stc.get(phys_port, "location")
                        logger.debug("PhysPort: host_name: %s, slot: %s, pg: %s, port_index: %s, location: %s" % (
                            hostname, slot, phys_pg, port_index, loc))
                        port_list.append(loc)
        return port_list

    def connect_chassis(self):
        resp = self.stc.perform("ConnectToChassis",
                                AddrList=[self.west_stcv["mgmt_ip"], self.east_stcv["mgmt_ip"]],
                                TimeoutInSec=120)
        assert resp["Status"] == "Completed!"

        return

    def configure_port(self, stcv):
        port = self.stc.create("port", under=self.project, location=stcv["port_location"])
        self.stc.perform("attachports", autoconnect=False, portList=port)

        dev = self.stc.create("emulateddevice", under=self.project, enablepingresponse=True, devicecount="1")

        ethiiif = self.stc.create("ethiiif", under=dev)
        self.stc.config(ethiiif, useDefaultPhyMac=True)

        ipv4if = self.stc.create("ipv4if",
                                 under=dev,
                                 usePortDefaultIpv4Gateway=False,
                                 resolveGatewayMac=True)
        self.stc.config(ipv4if, address=stcv["test_port_ip"])
        self.stc.config(ipv4if, gateway=stcv["gw_ip"])
        self.stc.config(ipv4if, prefixLength=24)

        self.stc.config(dev, affiliatedPort=port)
        self.stc.config(ipv4if, stackedOn=ethiiif)
        self.stc.config(dev, topLevelIf=ipv4if)
        self.stc.config(dev, primaryIf=ipv4if)

        # learn physical mac
        self.stc.perform("DetectSourceMacCommand", portlist=port)
        mac = self.stc.get(ethiiif, "SourceMac")
        if mac == "00:00:00:00:00:00" or mac == "00-00-00-00-00-00":
            logger.error("acquire default phy mac fail on port at %s" % stcv["port_location"])
        else:
            logger.info("acquire default phy mac success. port: %s, mac: %s" % (stcv["port_location"], mac))

        stcv["port"] = port
        stcv["ipv4if"] = ipv4if
        stcv["gen"] = self.stc.get(port, "children-generator")
        stcv["ana"] = self.stc.get(port, "children-analyzer")

        return

    def do_arp(self):
        # run arp to get gw mac
        resp = self.stc.perform("ArpNdStartCommand", handlelist=[self.west_stcv["port"], self.east_stcv["port"]], waitforarptofinish=True)
        assert resp["ArpNdState"] == "SUCCESSFUL"
        # TODO: show gw mac
        return

    def create_stream_block(self):
        self.west_stcv["strblk"] = self.stc.create("streamblock",
                                           under=self.west_stcv["port"],
                                           srcBinding=self.west_stcv["ipv4if"],
                                           dstBinding=self.east_stcv["ipv4if"])
        self.east_stcv["strblk"] = self.stc.create("streamblock",
                                           under=self.east_stcv["port"],
                                           srcBinding=self.east_stcv["ipv4if"],
                                           dstBinding=self.west_stcv["ipv4if"])

    def configure_traffic_load(self, stcv, port_rate, duration):
        gen = stcv["gen"]
        gen_conf = self.stc.get(gen, "children-generatorconfig")
        self.stc.config(gen_conf,
                        DurationMode="SECONDS",
                        Duration=duration,
                        LoadMode="FIXED",
                        FixedLoad=port_rate,
                        LoadUnit="PERCENT_LINE_RATE",
                        SchedulingMode="PORT_BASED")

    def subscrible_result(self):
        self.stc.perform(command="ResultsSubscribe",
                         parent=self.project,
                         resultparent=self.project,
                         configtype="StreamBlock",
                         resulttype="TxStreamResults")
        self.stc.perform(command="ResultsSubscribe",
                         parent=self.project,
                         resultparent=self.project,
                         configtype="StreamBlock",
                         resulttype="RxStreamSummaryResults")
        self.stc.perform(command="ResultsSubscribe",
                         parent=self.project,
                         resultparent=self.project,
                         configtype="GeneratorConfig",
                         resulttype="GeneratorPortResults")
        self.stc.perform(command="ResultsSubscribe",
                         parent=self.project,
                         resultparent=self.project,
                         configtype="AnalyzerConfig",
                         resulttype="AnalyzerPortResults")

    def run_traffic(self):
        self.stc.perform("resultsclearallcommand")

        gen_list = [self.west_stcv["gen"], self.east_stcv["gen"]]
        ana_list = [self.west_stcv["ana"], self.east_stcv["ana"]]
        self.stc.perform("AnalyzerStartCommand", Analyzerlist=ana_list)
        self.stc.perform("GeneratorStartCommand", GeneratorList=gen_list)

        self.stc.perform("Generatorwaitforstopcommand", GeneratorList=gen_list)

        self.stc.perform("AnalyzerStopCommand", Analyzerlist=ana_list)

    def collect_result(self, stcv):
        gen_res = self.stc.get(stcv["gen"], "children-generatorportresults")
        ana_res = self.stc.get(stcv["ana"], "children-analyzerportresults")

        result = {}
        tx_str_res = self.stc.get(stcv["strblk"], "children-txstreamresults")
        rx_str_res = self.stc.get(stcv["strblk"], "children-rxstreamsummaryresults")
        result["tx_frame_count"] = self.stc.get(tx_str_res, "FrameCount")
        result["tx_bit_count"] = self.stc.get(tx_str_res, "BitCount")
        result["rx_frame_count"] = self.stc.get(rx_str_res, "FrameCount")
        result["rx_bit_count"] = self.stc.get(rx_str_res, "BitCount")

        stcv["result"] = result

        #stcv["result"]["tx_count"] = self.stc.get(gen_res, "generatorsigframecount")
        # stcv["result"]["tx_rate"] = self.stc.get(gen_res, "generatorbitrate", "generatorframerate")
        # stcv["result"]["tx_duration"] = self.stc.get(gen_res, "txduration")
        #
        # stcv["result"]["rx_count"] = self.stc.get(ana_res, "sigframecount")
        # stcv["result"]["rx_rate"] = self.stc.get(ana_res, "totalbitrate", "totalframerate")

    def show_result(self):
        logger.info("west stcv result: \n %s", json.dumps(self.west_stcv["result"], indent=2))
        logger.info("east stcv result: \n %s", json.dumps(self.east_stcv["result"], indent=2))

    def run(self, port_rate=10, duration=10):
        self.connect_chassis()

        self.configure_port(self.west_stcv)
        self.configure_port(self.east_stcv)
        self.do_arp()

        self.create_stream_block()

        self.configure_traffic_load(self.west_stcv, port_rate, duration)
        self.configure_traffic_load(self.east_stcv, port_rate, duration)

        self.subscrible_result()

        self.run_traffic()

        self.collect_result(self.west_stcv)
        self.collect_result(self.east_stcv)

        return

if __name__ == "__main__":
    labserver_ip = "10.109.184.26"
    labserver_port = 30922
    stcv_west_ip = "172.18.2.78"
    stcv_east_ip = "172.18.2.79"

    stcv_west_test_port_ip = "192.168.10.26"
    stcv_east_test_port_ip = "192.168.10.27"

    dut_left_ip = "192.168.10.27"
    dut_right_ip = "192.168.10.26"

    test = SimpleTrafficTest(labserver_ip=labserver_ip,
                             stcv_west_mgmt_ip=stcv_west_ip,
                             stcv_west_test_port_ip=stcv_west_test_port_ip,
                             stcv_east_mgmt_ip=stcv_east_ip,
                             stcv_east_test_port_ip=stcv_east_test_port_ip,
                             dut_left_ip=dut_left_ip,
                             dut_right_ip=dut_right_ip,
                             labserver_port=labserver_port)
    try:
        test.run()
    except Exception as e:

        logger.debug(e)
    finally:
        test.__del__()

