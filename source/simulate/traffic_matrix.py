from simulate.flow import Flow

class TrafficMatrix:
    def __init__(self):
        self.data = {"all":{},"no-bronze":{}}
        self.flows = {}

    def add_data(self, src, dst, traffic, type):
        if src not in self.data[type]:
            self.data[type][src] = {}

        # aggregate traffic with the same OD pair for different priorities(GOLD, SILVER, BRONZE)
        try:
            self.data[type][src][dst] += traffic
        except:
            self.data[type][src][dst] = traffic

    def register_flow(self, flow_name, src, dst, traffic, cos):
        assert(flow_name not in self.flows)
        self.flows[flow_name] = Flow(flow_name, src, dst, traffic, cos)
        if cos!="BRONZE":
            self.add_data(src.name, dst.name, traffic, "no-bronze")
        self.add_data(src.name, dst.name, traffic, "all")
