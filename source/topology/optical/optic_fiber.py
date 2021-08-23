from topology.optical.optic_node import OpticNode

class OpticFiber:
    def __init__(self, name, src: OpticNode, dst: OpticNode, length,lease_flag=False,max_fp=None,lighted_fp=None,spectrum=None,\
        min_bw=None,max_bw=None):
        self.name = name
        self.src = src
        self.dst = dst
        self.length = length
        self.lease_flag = lease_flag

        # attributes for fibers owned: lease_flag=False
        self.max_fp = max_fp
        self.lighted_fp = lighted_fp
        self.spectrum = spectrum

        # attributes for fibers leased: lease_flag=True
        self.min_bw = min_bw
        self.max_bw = max_bw

        if lease_flag:
            assert(self.min_bw!=None)
            assert(self.max_bw!=None)
        else:
            assert(self.max_fp!=None)
            assert(self.spectrum!=None)
