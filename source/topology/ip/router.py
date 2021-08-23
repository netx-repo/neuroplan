from topology.utils.node import Node

class Router(Node):
    def __init__(self, name, l1_node:Node, stub:bool):
        super().__init__(name)
        self.l1_node = l1_node
        self.stub = stub


